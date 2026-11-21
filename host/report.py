"""Machine-readable conformance report (`fe-compatibility-report`, version 1).

The Fe checker has already decided the verdict, category, and location of every
listed mismatch. This module only presents those decisions:

* strict view: the exact raw bytes involved, as recorded;
* explanatory view: names and typed values taken from the ABI (function
  outputs, error and event signatures, state declarations). Explanations never
  change a verdict.

Output is deterministic: sorted keys, no timestamps. The number of listed
mismatches is bounded by the Fe checker (at most 8), and the total is reported.
"""
import hashlib
import json

from evm_chain import cast

FORMAT = 'fe-compatibility-report'
VERSION = 1


def canonical_type(item):
    if item['type'] == 'tuple':
        return '(' + ','.join(canonical_type(c) for c in item['components']) + ')'
    return item['type']


class Interface:
    """Name lookup built from one or more ABI JSON documents."""

    def __init__(self, *abis):
        self.functions, self.errors, self.events = {}, {}, {}
        for abi in abis:
            for e in abi:
                if e['type'] not in ('function', 'error', 'event'):
                    continue
                signature = f'{e["name"]}({",".join(canonical_type(i) for i in e["inputs"])})'
                if e['type'] == 'function':
                    self.functions[signature] = e
                elif e['type'] == 'error':
                    self.errors[cast('sig', signature).lower()] = (signature, e)
                else:
                    self.events[cast('sig-event', signature).lower()] = (signature, e)


def decode(word, kind):
    """Typed view of one 32-byte word (an int as an unsigned word)."""
    value = int(word)
    if kind in ('address',):
        return '0x' + f'{value:064x}'[24:] if value < (1 << 160) else f'0x{value:064x} (not an address)'
    if kind == 'bool':
        return {0: 'false', 1: 'true'}.get(value, f'{value} (not a bool)')
    if kind.startswith('int'):
        bits = int(kind[3:] or 256)
        signed = value - (1 << 256) if value >= (1 << 255) else value
        return str(signed) if -(1 << (bits - 1)) <= signed < (1 << (bits - 1)) else f'0x{value:064x} (out of range)'
    if kind.startswith('uint'):
        return str(value)
    return f'0x{value:064x}'


def revert_name(interface, returndata):
    selector = returndata[:10]
    if len(returndata) < 10:
        return f'revert with {(len(returndata) - 2) // 2} bytes'
    name = interface.errors.get(selector, (f'unknown error {selector}',))[0]
    return f'revert {name}'


def outcome(interface, observation):
    return 'success' if observation['success'] else revert_name(interface, observation['returndata'])


def event_name(interface, log):
    if not log or not log['topics']:
        return 'anonymous log' if log else None
    return interface.events.get(log['topics'][0], (f'unknown event {log["topics"][0]}',))[0]


def explain(interface, mismatch, left, right, action, state_decls):
    c, slot, index = mismatch['category'], mismatch['slot'], mismatch['index']
    a, b = mismatch['left'], mismatch['right']
    if c == 'status':
        return {'what': 'one implementation succeeded and the other reverted',
                'left': outcome(interface, left), 'right': outcome(interface, right)}
    if c in ('returndata-length',):
        return {'what': 'different returndata length', 'left_bytes': a, 'right_bytes': b,
                'left': outcome(interface, left), 'right': outcome(interface, right)}
    if c == 'returndata-byte' and left['success']:
        outputs = interface.functions.get(action['call'], {}).get('outputs', [])
        types = [x for o in outputs for x in (canonical_type(o)[1:-1].split(',') if o['type'] == 'tuple'
                                                else [canonical_type(o)])]
        kind = types[slot] if slot < len(types) and 'bytes' not in types else 'bytes32'
        return {'what': f'return value {slot} ({kind}) differs at byte {index}',
                'left': decode(a, kind), 'right': decode(b, kind)}
    if c == 'returndata-byte':
        return {'what': f'revert data differs at byte {index}', 'left': a, 'right': b}
    if c == 'error-selector':
        name = lambda s: interface.errors.get(f'0x{int(s):08x}', (f'unknown error 0x{int(s):08x}',))[0]
        return {'what': 'different custom error', 'left': name(a), 'right': name(b)}
    if c == 'error-argument':
        signature, entry = interface.errors.get(left['returndata'][:10], ('unknown error', {'inputs': []}))
        inputs = entry['inputs']
        arg = inputs[slot] if slot < len(inputs) else {'name': f'#{slot}', 'type': 'bytes32'}
        return {'what': f'{signature}: argument {slot} `{arg["name"]}` ({arg["type"]}) differs',
                'left': decode(a, arg['type']), 'right': decode(b, arg['type'])}
    if c in ('log-missing', 'log-extra', 'log-reordered', 'log-count'):
        side = right if c == 'log-extra' else left
        log = side['logs'][index] if index < len(side['logs']) else None
        what = {'log-missing': f'log {index} ({event_name(interface, log)}) is missing on the right',
                'log-extra': f'extra log {index} ({event_name(interface, log)}) on the right',
                'log-reordered': f'same logs in a different order, first at position {index}',
                'log-count': 'different numbers of logs, not explained by one insertion or deletion'}[c]
        return {'what': what, 'left_events': [event_name(interface, l) for l in left['logs']],
                'right_events': [event_name(interface, l) for l in right['logs']]}
    if c in ('log-emitter', 'topic-count', 'topic', 'log-data-length', 'log-data-byte'):
        log = left['logs'][mismatch['log']]
        signature, entry = interface.events.get(log['topics'][0] if log['topics'] else '', ('unknown event', None))
        inputs = entry['inputs'] if entry else []
        indexed = [i for i in inputs if i.get('indexed')]
        data = [i for i in inputs if not i.get('indexed')]
        if c == 'topic':
            param = indexed[index - 1] if 0 < index <= len(indexed) else None
            what = (f'{signature}: event signature topic differs' if index == 0 else
                    f'{signature}: indexed `{param["name"] if param else index}` differs')
            kind = param['type'] if param else 'bytes32'
            return {'what': what, 'left': decode(a, kind), 'right': decode(b, kind)}
        if c == 'log-data-byte':
            param = data[slot] if slot < len(data) else {'name': f'word {slot}', 'type': 'bytes32'}
            return {'what': f'{signature}: data `{param["name"]}` ({param["type"]}) differs at byte {index}',
                    'left': decode(a, param['type']), 'right': decode(b, param['type'])}
        if c == 'topic-count':
            return {'what': f'{signature}: {a} topics vs {b} (an indexed flag differs)', 'left': a, 'right': b}
        if c == 'log-emitter':
            return {'what': f'{signature}: emitted by a different contract', 'left': decode(a, 'address'),
                    'right': decode(b, 'address')}
        return {'what': f'{signature}: data length {a} vs {b} bytes', 'left': a, 'right': b}
    if c.startswith('state-'):
        name, signature, kind = state_decls[slot] if slot < len(state_decls) else (f'#{slot}', '?', 'word')
        solidity_kind = {'uint': 'uint256', 'int': 'int256', 'address': 'address', 'bool': 'bool'}.get(kind, 'bytes32')
        if c == 'state-value':
            return {'what': f'state `{name}` ({signature}) differs after the action', 'left': decode(a, solidity_kind),
                    'right': decode(b, solidity_kind)}
        return {'what': f'state {c[6:]} differs', 'left': a, 'right': b}
    return {'what': c, 'left': a, 'right': b}


def strict(mismatch, left, right):
    c = mismatch['category']
    if c.startswith('state-'):
        pick = lambda o: o.get('state', [])[mismatch['slot']] if mismatch['slot'] < len(o.get('state', [])) else None
        return {'left_state': pick(left), 'right_state': pick(right)}
    if c.startswith('log') or c in ('topic', 'topic-count'):
        return {'left_logs': left['logs'], 'right_logs': right['logs']}
    return {'left_success': left['success'], 'right_success': right['success'],
            'left_returndata': left['returndata'], 'right_returndata': right['returndata']}


def digest(record):
    return hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def build(corpus, mode, left, right, decision, interface, state_decls, labels):
    """left/right: raw execution records (v2); decision: fecheck.sequence(...); labels: per-step action dicts."""
    mismatches = []
    for m in decision.get('mismatches', []):
        if m['deployment']:
            a, b, action = left['deployment'], right['deployment'], {'call': 'deployment'}
        else:
            a, b, action = left['steps'][m['step']], right['steps'][m['step']], labels[m['step']]
        mismatches.append({'step': None if m['deployment'] else m['step'], 'deployment': m['deployment'],
                           'action': action, 'category': m['category'],
                           'location': {'log': m['log'], 'index': m['index'], 'slot': m['slot']},
                           'fe': {'left': m['left'], 'right': m['right']},
                           'strict': strict(m, a, b),
                           'explanation': explain(interface, m, a, b, action, state_decls)})
    verdict = decision['verdict']
    claim = {'match': f'No mismatch observed for corpus {corpus} under this configuration. '
                      'This is not an equivalence proof.',
             'mismatch': f'{decision["mismatching_steps"]} of {decision["steps_compared"]} steps differ; '
                         'the first divergence is listed first.',
             'not-comparable': 'A deployment failed; no behavior was compared.',
             'malformed': 'An observation was malformed; this is a harness or transport problem, not a verdict.'}[verdict]
    report = {
        'format': FORMAT, 'version': VERSION, 'mode': mode, 'corpus': corpus,
        'configuration': {side: {'implementation': r['implementation'], 'target': r['target'], 'world': r['world'],
                                 'deployed_runtime_sha256': r['deployment'].get('runtime_code_sha256')}
                          for side, r in (('left', left), ('right', right))},
        'tools': left['tools'], 'environment': left.get('environment'),
        'raw_records_sha256': {'left': digest(left), 'right': digest(right)},
        'decision': {k: decision[k] for k in ('checker', 'verdict', 'steps_compared', 'mismatching_steps', 'listed',
                                              'truncated')},
        'claim': claim + ' ABI declarations are compared separately (abi_declarations).',
        'state_declared': [{'name': n, 'getter': s, 'kind': k} for n, s, k in state_decls],
        'mismatches': mismatches,
        'gas_used': {'left': [s['gas_used'] for s in left['steps']], 'right': [s['gas_used'] for s in right['steps']],
                     'note': 'reported only; gas is never compared'},
    }
    if 'malformed' in decision:
        report['malformed'] = decision['malformed']
    if 'deployment_succeeded' in decision:
        report['deployment_succeeded'] = decision['deployment_succeeded']
    return report


def render(report):
    return json.dumps(report, indent=2, sort_keys=True) + '\n'
