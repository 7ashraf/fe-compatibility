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
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import BUILD, InfrastructureError, load_stamp  # noqa: E402
from evm_chain import RpcError, cast  # noqa: E402
import fecheck  # noqa: E402
from world import World, GENESIS  # noqa: E402

ACTIONS = (('add(uint256)', 5), ('add(uint256)', 0), ('add(uint256)', 200), ('add(uint256)', 100), ('total()', None))
SIGNATURES = {'function': {'add(uint256)', 'total()'}, 'event': {'Added(address,uint256,uint256)'},
              'error': {'EmptyQuantity()', 'TooLarge(uint256,uint256)'}}
STRICT = {'return_words': [], 'topics': [], 'data_words': []}


def canonical_abi(path):
    entries = {'function': set(), 'event': set(), 'error': set()}
    for item in json.loads(path.read_text()):
        if item['type'] in entries:
            entries[item['type']].add(f"{item['name']}({','.join(i['type'] for i in item['inputs'])})")
    return entries


def observe(target, stamp):
    """Deploy in a fresh world and run ACTIONS; return the raw execution record (v2)."""
    identity = stamp['targets'][target]
    creation = '0x' + (BUILD / identity['creation']).read_text().strip().removeprefix('0x')
    # Phase 0 sends every call from account 0, which is also the deployer.
    with World(deployer=0, caller=0) as world:
        deployment = world.deploy(creation)
        if not deployment['success']:
            raise InfrastructureError(f'{target}: deployment failed')
        steps = []
        for index, (signature, argument) in enumerate(ACTIONS):
            data = cast('calldata', signature, *([] if argument is None else [argument]))
            observation = world.call(data)
            steps.append({'index': index, 'call': signature, 'argument': None if argument is None else str(argument),
                          'calldata': data, **observation})
        return {'format': 'fe-compatibility-raw-execution', 'version': 2, 'implementation': target,
                'target': identity, 'tools': world.versions, 'world': dict(world.roles),
                'environment': {'hardfork': 'osaka', 'chain_id': 31337, 'genesis_timestamp': GENESIS,
                                'base_fee': 0, 'gas_limit_per_tx': 2_000_000, 'gas_price': 1,
                                'sender_nonce_at_deploy': 0,
                                'mining': 'one mined transaction per block, scheduled timestamps'},
                'deployment': deployment,
                'returndata_source': 'debug_traceTransaction returnValue, cross-checked against eth_call at the '
                                     'parent block',
                'steps': steps}


def check(left, right):
    """Send both raw records to the native Fe checker and return its decision."""
    if len(left['steps']) != len(right['steps']):
        raise InfrastructureError('Records have different step counts')
    decision = fecheck.sequence(left['deployment'], right['deployment'],
                                [(STRICT, True, a, b) for a, b in zip(left['steps'], right['steps'])])
    if 'first_divergence' in decision:
        d = decision['first_divergence']
        step = left['steps'][d['step']]
        d.update(call=step['call'], argument=step['argument'], left_returndata=step['returndata'],
                 right_returndata=right['steps'][d['step']]['returndata'])
    return decision, None


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
        decision, _ = check(left, right)
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
