#!/usr/bin/env python3
"""Phase 0: execute the Meter v0 sequence against two implementations, each in
its own fresh pinned Anvil (Osaka) world, capture raw observations, and let the
native Fe checker decide whether they match.

Python only drives the chains and moves bytes. It never decides equality: the
verdict, the category, and the first divergence come from the Fe checker.

Exit status: 0 no mismatch, 1 mismatch reported by Fe, 2 invalid input,
3 infrastructure error (tool or build mismatch, RPC failure, transport
disagreement, malformed observation).
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, BUILD, CHECKER, InfrastructureError, load_stamp  # noqa: E402
from evm_chain import LocalChain, RpcError, cast  # noqa: E402

GENESIS = 1700000000
ACTIONS = (('add(uint256)', 5), ('add(uint256)', 0), ('add(uint256)', 200), ('add(uint256)', 100), ('total()', None))
CATEGORIES = {1: 'status', 2: 'returndata-length', 3: 'returndata-byte', 4: 'log-count', 5: 'log-emitter',
              6: 'topic-count', 7: 'topic', 8: 'log-data-length', 9: 'log-data-byte'}
SIGNATURES = {'function': {'add(uint256)', 'total()'}, 'event': {'Added(address,uint256,uint256)'},
              'error': {'EmptyQuantity()', 'TooLarge(uint256,uint256)'}}


def canonical_abi(path):
    entries = {'function': set(), 'event': set(), 'error': set()}
    for item in json.loads(path.read_text()):
        if item['type'] in entries:
            entries[item['type']].add(f"{item['name']}({','.join(i['type'] for i in item['inputs'])})")
    return entries


def raw_hex(value):
    text = (value or '').removeprefix('0x')
    if len(text) % 2:
        raise InfrastructureError('Odd-length hex from RPC')
    bytes.fromhex(text)
    return '0x' + text.lower()


def observe(target, stamp):
    """Deploy in a fresh world and run ACTIONS; return the raw execution record."""
    identity = stamp['targets'][target]
    creation = '0x' + (BUILD / identity['creation']).read_text().strip().removeprefix('0x')
    with LocalChain(ROOT) as chain:
        sender = chain.accounts[0]
        chain.rpc('evm_setNextBlockTimestamp', [GENESIS + 1])
        chain.send('deploy', data=creation, success=True)
        receipt = chain.receipts[-1]['receipt']
        address = receipt['contractAddress']
        runtime = chain.rpc('eth_getCode', [address, 'latest'])
        steps = []
        for index, (signature, argument) in enumerate(ACTIONS):
            data = cast('calldata', signature, *([] if argument is None else [argument]))
            timestamp = GENESIS + 2 + index
            chain.rpc('evm_setNextBlockTimestamp', [timestamp])
            chain.send(f'step{index}', to=address, data=data, sender=sender, success=None)
            receipt = chain.receipts[-1]['receipt']
            block = chain.rpc('eth_getBlockByNumber', [receipt['blockNumber'], False])
            if int(block['timestamp'], 16) != timestamp:
                raise InfrastructureError('Mined timestamp differs from the scheduled one')
            success = int(receipt['status'], 16) == 1
            trace = chain.rpc('debug_traceTransaction', [receipt['transactionHash'],
                              {'disableStorage': True, 'disableMemory': True, 'disableStack': True}])
            if bool(trace.get('failed')) == success:
                raise InfrastructureError('Receipt status and trace disagree')
            returndata = raw_hex(trace.get('returnValue', ''))
            # Independent second path: replay the call against the parent block.
            parent = hex(int(receipt['blockNumber'], 16) - 1)
            call = {'from': sender, 'to': address, 'data': data, 'gas': hex(2_000_000)}
            try:
                via_call, call_success = raw_hex(chain.rpc('eth_call', [call, parent])), True
            except RpcError as error:
                via_call, call_success = raw_hex((error.error or {}).get('data', '')), False
            if (via_call, call_success) != (returndata, success):
                raise InfrastructureError(f'Step {index}: trace and eth_call returndata disagree')
            steps.append({
                'index': index, 'call': signature, 'argument': None if argument is None else str(argument),
                'calldata': data, 'block': int(receipt['blockNumber'], 16), 'timestamp': timestamp,
                'success': success, 'returndata': returndata, 'returndata_via_eth_call': via_call,
                'logs': [{'address': log['address'].lower(), 'topics': [t.lower() for t in log['topics']],
                          'data': raw_hex(log['data'])} for log in receipt['logs']],
                'gas_used': int(receipt['gasUsed'], 16),
            })
        return {'format': 'fe-compatibility-raw-execution-v1', 'implementation': target,
                'target': identity, 'tools': chain.versions,
                'environment': {'hardfork': 'osaka', 'chain_id': 31337, 'genesis_timestamp': GENESIS,
                                'base_fee': 0, 'gas_limit_per_tx': 2_000_000, 'gas_price': 1,
                                'sender': sender.lower(), 'sender_nonce_at_deploy': 0,
                                'mining': 'one mined transaction per block, scheduled timestamps'},
                'deployment': {'address': address.lower(), 'runtime_code_sha256': hashlib.sha256(bytes.fromhex(runtime[2:])).hexdigest()},
                'returndata_source': 'debug_traceTransaction returnValue, cross-checked against eth_call at the '
                                     'parent block',
                'steps': steps}


def payload_words(hex_text):
    raw = bytes.fromhex(hex_text[2:])
    padded = raw + b'\0' * (-len(raw) % 32)
    return [len(raw)] + [int.from_bytes(padded[i:i + 32], 'big') for i in range(0, len(padded), 32)]


def observation_words(step):
    words = [1 if step['success'] else 0, *payload_words(step['returndata']), len(step['logs'])]
    for log in step['logs']:
        words += [int(log['address'], 16), len(log['topics']), *(int(t, 16) for t in log['topics']),
                  *payload_words(log['data'])]
    return words


def check(left, right):
    """Send both raw records to the native Fe checker and return its decision."""
    if len(left['steps']) != len(right['steps']):
        raise InfrastructureError('Records have different step counts')
    words = [1, len(left['steps'])]
    for a, b in zip(left['steps'], right['steps']):
        words += observation_words(a) + observation_words(b)
    frame = ' '.join(map(str, words))
    try:
        result = subprocess.run([str(CHECKER)], input=frame, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise InfrastructureError(f'Fe checker failed to run: {error}') from error
    if result.returncode != 0:
        raise InfrastructureError(f'Fe checker rejected the frame (exit {result.returncode})')
    reply = result.stdout.split()
    if len(reply) != 9 or reply[0] != '1' or not all(r.isdigit() for r in reply):
        raise InfrastructureError(f'Malformed Fe checker reply: {result.stdout!r}')
    verdict, steps, step, category, log, index, a, b = map(int, reply[1:])
    if verdict == 2:
        raise InfrastructureError(f'Fe checker: malformed observation at step {step}')
    if verdict not in (0, 1) or steps != len(left['steps']):
        raise InfrastructureError(f'Unexpected Fe checker reply: {result.stdout!r}')
    decision = {'checker': 'native Fe compat_checker protocol 1', 'frame_words': len(words),
                'steps_compared': steps, 'verdict': 'match' if verdict == 0 else 'mismatch'}
    if verdict == 1:
        decision['first_divergence'] = {
            'step': step, 'call': left['steps'][step]['call'], 'argument': left['steps'][step]['argument'],
            'category': CATEGORIES[category], 'log': log, 'index': index, 'left': str(a), 'right': str(b),
            'left_returndata': left['steps'][step]['returndata'], 'right_returndata': right['steps'][step]['returndata']}
    return decision, frame


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--left', default='solidity', choices=('solidity', 'fe', 'fe-faulty'))
    parser.add_argument('--right', default='fe', choices=('solidity', 'fe', 'fe-faulty'))
    parser.add_argument('--record-dir', type=Path, help='write the two raw execution records here')
    args = parser.parse_args()
    try:
        stamp = load_stamp()
        abis = {t: canonical_abi(BUILD / stamp['targets'][t]['abi']) for t in (args.left, args.right)}
        if any(abi != SIGNATURES for abi in abis.values()):
            raise InfrastructureError(f'Compiled ABI differs from spec/meter-v0.md: {abis}')
        left, right = observe(args.left, stamp), observe(args.right, stamp)
        if left['deployment']['address'] != right['deployment']['address']:
            raise InfrastructureError('Worlds are not equivalent: deployment addresses differ')
        decision, frame = check(left, right)
        if args.record_dir:
            args.record_dir.mkdir(parents=True, exist_ok=True)
            for record in (left, right):
                (args.record_dir / f'raw-{record["implementation"]}.json').write_text(json.dumps(record, indent=2) + '\n')
        report = {'format': 'fe-compatibility-phase0-report-v1', 'mode': 'behavioral conformance (strict raw bytes)',
                  'corpus': 'spec/meter-v0.md Phase 0 sequence (5 calls)', 'left': args.left, 'right': args.right,
                  'claim': ('No mismatch observed for this corpus under this configuration; this is not an '
                            'equivalence proof.' if decision['verdict'] == 'match' else
                            'Mismatch observed; see first_divergence.'),
                  **decision, 'gas_used': {'left': [s['gas_used'] for s in left['steps']],
                                           'right': [s['gas_used'] for s in right['steps']],
                                           'note': 'reported only; gas is not compared'}}
        print(json.dumps(report, indent=2))
        return 0 if decision['verdict'] == 'match' else 1
    except (InfrastructureError, RpcError, OSError, subprocess.SubprocessError, AssertionError) as error:
        print(json.dumps({'verdict': 'infrastructure', 'error': str(error)}, indent=2))
        return 3


if __name__ == '__main__':
    sys.exit(main())
