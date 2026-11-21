#!/usr/bin/env python3
"""Execute the Meter v0 sequence against two implementations, each in its own
fresh pinned Anvil (Osaka) world, capture raw observations (including the
public `total()` state after every call), let the native Fe checker decide,
and print a `fe-compatibility-report` v1 (spec/report.md).

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
from common import BUILD, VARIANTS, InfrastructureError, load_stamp  # noqa: E402
from evm_chain import RpcError, cast  # noqa: E402
import fecheck  # noqa: E402
import report as reporting  # noqa: E402
from world import World, GENESIS  # noqa: E402

ACTIONS = (('add(uint256)', 5), ('add(uint256)', 0), ('add(uint256)', 200), ('add(uint256)', 100), ('total()', None))
SIGNATURES = {'function': {'add(uint256)', 'total()'}, 'event': {'Added(address,uint256,uint256)'},
              'error': {'EmptyQuantity()', 'TooLarge(uint256,uint256)'}}
STRICT = {'return_words': [], 'topics': [], 'data_words': []}
# Public state read after every call: (name, getter, kind).
STATE = (('total', 'total()', 'uint'),)
TARGETS = ('solidity', 'fe', *VARIANTS)


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
            observation = world.call(data, state=STATE)
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


def check(left, right, raise_malformed=True):
    """Send both raw records to the native Fe checker and return its decision."""
    if len(left['steps']) != len(right['steps']):
        raise InfrastructureError('Records have different step counts')
    return fecheck.sequence(left['deployment'], right['deployment'],
                            [(STRICT, True, a, b) for a, b in zip(left['steps'], right['steps'])],
                            raise_malformed=raise_malformed), None


def declarations(left, right):
    """ABI declaration conformance against spec/meter-v0.md. A difference is a finding, not a harness error."""
    out = {'match': left == SIGNATURES and right == SIGNATURES, 'spec': 'spec/meter-v0.md'}
    for side, abi in (('left', left), ('right', right)):
        out[side] = {'missing': sorted(s for k in SIGNATURES for s in SIGNATURES[k] - abi[k]),
                     'unexpected': sorted(s for k in SIGNATURES for s in abi[k] - SIGNATURES[k])}
    return out


def build_report(left, right, decision, stamp):
    abis = [json.loads((BUILD / stamp['targets'][r['implementation']]['abi']).read_text()) for r in (left, right)]
    labels = [{'call': s['call'], 'argument': s['argument']} for s in left['steps']]
    return reporting.build('meter-v0 (5 calls)', 'behavioral conformance (strict)', left, right, decision,
                           reporting.Interface(*abis), STATE, labels)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--left', default='solidity', choices=TARGETS)
    parser.add_argument('--right', default='fe', choices=TARGETS)
    parser.add_argument('--record-dir', type=Path, help='write the two raw execution records here')
    args = parser.parse_args()
    try:
        stamp = load_stamp()
        abis = {t: canonical_abi(BUILD / stamp['targets'][t]['abi']) for t in (args.left, args.right)}
        left, right = observe(args.left, stamp), observe(args.right, stamp)
        if left['deployment']['address'] != right['deployment']['address']:
            raise InfrastructureError('Worlds are not equivalent: deployment addresses differ')
        decision, _ = check(left, right)
        if args.record_dir:
            args.record_dir.mkdir(parents=True, exist_ok=True)
            for record in (left, right):
                (args.record_dir / f'raw-{record["implementation"]}.json').write_text(json.dumps(record, indent=2) + '\n')
        report = build_report(left, right, decision, stamp)
        report['abi_declarations'] = declarations(abis[args.left], abis[args.right])
        print(reporting.render(report), end='')
        return 0 if decision['verdict'] == 'match' and report['abi_declarations']['match'] else 1
    except (InfrastructureError, RpcError, OSError, subprocess.SubprocessError, AssertionError) as error:
        print(json.dumps({'verdict': 'infrastructure', 'error': str(error)}, indent=2))
        return 3


if __name__ == '__main__':
    sys.exit(main())
