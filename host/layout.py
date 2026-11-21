#!/usr/bin/env python3
"""Phase 4: explicit layout conformance for spec/layout-v1.md.

For each implementation, in its own fresh pinned Anvil world, the runner runs
the actions in fixtures/layout/packed-v1.json and records, per action:
  * raw slot 0 and slot 1 before and after (eth_getStorageAt);
  * every declared key's entry, at the slot `cast index` derives (independent
    of both compilers);
  * every slot the transaction wrote (SSTORE operands from the opcode trace).
The Fe layout validator (native request kind 4) checks the schema, then every
action: neighbor preservation, field values, mapping entries, and write set.
The Fe engine also compares the two implementations' raw slots and getter
returndata step by step (layout differential).

Exit status: 0 both implementations conform and match each other, 1 a layout
or behavior difference, 3 infrastructure error.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, BUILD, InfrastructureError, load_stamp, sha  # noqa: E402
from evm_chain import RpcError, cast  # noqa: E402
import fecheck  # noqa: E402
from world import World, raw_hex  # noqa: E402

FIXTURE = ROOT / 'fixtures/layout/packed-v1.json'
KINDS = {'uint': 0, 'address': 1, 'bool': 2}
CATEGORIES = {0: 'valid', 1: 'too-many', 2: 'width', 3: 'out-of-range', 4: 'overlap', 5: 'root-reserved',
              6: 'duplicate-root', 7: 'missing-slot', 8: 'neighbor', 9: 'field-value', 10: 'mapping-entry',
              11: 'undeclared-write'}
STRICT = {'return_words': [], 'topics': [], 'data_words': []}


def load(path=FIXTURE):
    data = json.loads(Path(path).read_text())
    if data.get('format') != 'fe-compatibility-layout' or data.get('schema_version') != 1:
        raise InfrastructureError('Unsupported layout fixture')
    return data


def entry_slot(key, root):
    return int(cast('index', 'address', key, root), 16)


def storage(world, slot):
    return int(world.chain.rpc('eth_getStorageAt', [world.roles['target'], hex(slot), 'latest']), 16)


def sstores(world, tx_hash):
    """Slots written by SSTOREs executed in the target's own frame (depth 1)."""
    trace = world.chain.rpc('debug_traceTransaction', [tx_hash, {'disableStorage': True, 'disableMemory': True,
                                                                 'disableStack': False}])
    slots = []
    for log in trace.get('structLogs', []):
        if log['op'] == 'SSTORE' and log['depth'] == 1:
            slot = int(log['stack'][-1], 16)
            if slot not in slots:
                slots.append(slot)
    return slots


def run(target, fixture, stamp):
    schema = fixture['schema']
    root = int(schema['mappings'][0]['root'])
    keys = fixture['keys']
    entries = {k: entry_slot(k, root) for k in keys}
    creation = '0x' + (BUILD / stamp['targets'][target]['creation']).read_text().strip().removeprefix('0x')
    model = {f['name']: '0' for f in schema['fields']}
    balances = {k: 0 for k in keys}
    steps = []
    with World(deployer=0, caller=1) as world:
        deployment = world.deploy(creation)
        if not deployment['success']:
            raise InfrastructureError(f'{target}: deployment failed')
        state = [{'name': 'slot0', 'kind': 'word', 'getter': None}, {'name': 'slot1', 'kind': 'word', 'getter': None}]
        for action in fixture['actions']:
            before = {0: storage(world, 0), 1: storage(world, 1)}
            data = cast('calldata', action['call'], *action['args']).lower()
            observation = world.call(data)
            tx = world.chain.receipts[-1]['receipt']['transactionHash']
            for name, value in action['set'].items():
                if name in model:
                    model[name] = value
                else:
                    balances[name] = int(value)
            after = {0: storage(world, 0), 1: storage(world, 1)}
            observed_entries = {k: storage(world, s) for k, s in entries.items()}
            observation['state'] = (
                [{'name': f'slot{s}', 'kind': 'word', 'value': str(after[s])} for s in (0, 1)]
                + [{'name': f'balances[{k}] @ {hex(entries[k])}', 'kind': 'word', 'value': str(observed_entries[k])}
                   for k in keys])
            steps.append({'call': action['call'], 'argument': json.dumps(action['args']), 'calldata': data,
                          'written': action['writes'], 'before': {str(k): str(v) for k, v in before.items()},
                          'sstore_slots': [hex(s) for s in sstores(world, tx)],
                          'expected_fields': dict(model), 'expected_entries': {k: str(v) for k, v in balances.items()},
                          **observation})
        return {'format': 'fe-compatibility-raw-execution', 'version': 2, 'implementation': target,
                'target': stamp['targets'][target], 'tools': world.versions, 'world': dict(world.roles),
                'deployment': deployment, 'entry_slots': {k: hex(s) for k, s in entries.items()}, 'steps': steps}


def field_value(field, text):
    if field['kind'] == 'address':
        return int(text, 16)
    return int(text)


def layout_check(fixture, record, schema=None):
    """Fe validates the schema and every action of one implementation (native request kind 4)."""
    schema = schema or fixture['schema']
    fields = schema['fields']
    names = [f['name'] for f in fields]
    words = [3, 4, len(fields)]
    for f in fields:
        words += [int(f['slot']), f['offset'], f['bytes'], KINDS[f['kind']]]
    roots = [int(m['root']) for m in schema['mappings']]
    words += [len(roots), *roots, len(record['steps'])]
    entries = record['entry_slots']
    for step in record['steps']:
        words += [2, 0, int(step['before']['0']), int(step['state'][0]['value']),
                  1, int(step['before']['1']), int(step['state'][1]['value'])]
        written = names.index(step['written']) if step['written'] in names else 255
        words += [written, *(field_value(f, step['expected_fields'][f['name']]) for f in fields)]
        words += [len(entries)]
        for i, (key, slot) in enumerate(entries.items()):
            words += [int(slot, 16), int(step['state'][2 + i]['value']), int(step['expected_entries'][key])]
        words += [len(step['sstore_slots']), *(int(s, 16) for s in step['sstore_slots'])]
    reply, _ = fecheck.run(words)
    if len(reply) != 7 or reply[:2] != [3, 4] or reply[2] not in CATEGORIES:
        raise InfrastructureError(f'Unexpected Fe layout reply: {reply}')
    category, step, index, left, right = reply[2:]
    out = {'checker': 'native Fe compat_checker protocol 3, kind 4', 'verdict': 'conforms' if category == 0 else
           ('invalid-schema' if category <= 6 else 'violation'), 'category': CATEGORIES[category]}
    if category:
        out.update(step=step if category > 6 else None, index=index, left=str(left), right=str(right))
        if category == 8:
            out['explanation'] = (f'action {step} ({record["steps"][step]["call"]}) changed byte {index} of slot 0, '
                                  f'outside the written field {record["steps"][step]["written"]}')
        elif category == 9:
            out['explanation'] = f'field {names[index]} reads {right}, expected {left}, after action {step}'
        elif category == 10:
            out['explanation'] = (f'entry for key {list(entries)[index]} at {list(entries.values())[index]} holds '
                                  f'{right}, expected {left}, after action {step}')
        elif category == 11:
            out['explanation'] = f'action {step} wrote undeclared slot {hex(right)}'
    out['scope'] = {'slots': sorted({int(f['slot']) for f in fields} | set(roots)),
                    'fields': [f'{f["name"]}: slot {f["slot"]} offset {f["offset"]} width {f["bytes"]} ({f["kind"]})'
                               for f in fields],
                    'mapping_keys': {k: v for k, v in entries.items()}, 'actions': len(record['steps'])}
    return out


def differential(left, right):
    return fecheck.sequence(left['deployment'], right['deployment'],
                            [(STRICT, True, a, b) for a, b in zip(left['steps'], right['steps'])])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--left', default='solidity-layout')
    parser.add_argument('--right', default='fe-layout')
    parser.add_argument('--record-dir', type=Path)
    args = parser.parse_args()
    try:
        fixture = load()
        stamp = load_stamp()
        left, right = run(args.left, fixture, stamp), run(args.right, fixture, stamp)
        out = {'format': 'fe-compatibility-layout-run-v1', 'fixture_sha256': sha(FIXTURE), 'left': args.left,
               'right': args.right, 'layout': {'left': layout_check(fixture, left), 'right': layout_check(fixture, right)},
               'differential': differential(left, right)}
        if args.record_dir:
            args.record_dir.mkdir(parents=True, exist_ok=True)
            for r in (left, right):
                (args.record_dir / f'raw-{r["implementation"]}.json').write_text(json.dumps(r, indent=2) + '\n')
        print(json.dumps(out, indent=2, sort_keys=True))
        ok = all(v['verdict'] == 'conforms' for v in out['layout'].values()) and \
            out['differential']['verdict'] == 'match'
        return 0 if ok else 1
    except (InfrastructureError, RpcError, OSError, KeyError) as error:
        print(json.dumps({'verdict': 'infrastructure', 'error': f'{type(error).__name__}: {error}'}, indent=2))
        return 3


if __name__ == '__main__':
    sys.exit(main())
