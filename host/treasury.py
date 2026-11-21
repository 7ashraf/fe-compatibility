#!/usr/bin/env python3
"""Phase 3: differential treasury execution over the frozen v0 behavioral corpus.

For every scenario in fixtures/behavior/treasury-v0.json, each implementation
gets its own fresh pinned Anvil (Osaka) world: the same actors, deployment
order, addresses, schedule, and funding. After every action the runner
records status, exact returndata, ordered logs, and 12 typed state fields
(nextGrantId, treasury balance, grant 1, grant 2 spent/active, payee balance).

The Fe checker decides two things:
  * spec oracle: each implementation's status, exact returndata, and exact
    events against the outcomes written from the spec (compiler rejections
    are compared by status only);
  * differential: left vs right step by step, including state, with a
    fe-compatibility-report v1 per scenario.

Exit status: 0 both implementations meet the spec oracle and match each other;
1 a conformance difference; 2 invalid corpus; 3 infrastructure error.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, BUILD, InfrastructureError, load_stamp, sha  # noqa: E402
from evm_chain import RpcError, cast  # noqa: E402
import fecheck  # noqa: E402
import report as reporting  # noqa: E402
from world import World  # noqa: E402

CORPUS = ROOT / 'fixtures/behavior/treasury-v0.json'
FROZEN_ABI = ROOT / 'spec/vendor/treasury-v0/treasury-v0.abi.json'
HARNESS = {'rejecting': 'harness-RejectingRecipient', 'reentrant': 'harness-ReentrantRecipient',
           'batcher': 'harness-Batcher'}
MAX = str(2**256 - 1)
STRICT = {'return_words': [], 'topics': [], 'data_words': []}
EXPECTED_DEPLOYMENT = {'success': True, 'checker_returndata': '0x', 'logs': []}


class CaseError(ValueError):
    pass


def load(path=CORPUS):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as error:
        raise CaseError(f'Unreadable corpus: {error}') from error
    keys = {'format', 'schema_version', 'interface', 'interface_sha256', 'actors', 'deployment', 'state', 'scenarios',
            'provenance'}
    if not isinstance(data, dict) or set(data) != keys:
        raise CaseError(f'Corpus must have exactly {sorted(keys)}')
    if data['format'] != 'fe-compatibility-scenarios' or type(data['schema_version']) is not int \
            or data['schema_version'] != 1:
        raise CaseError('Unsupported corpus format or version')
    if data['interface_sha256'] != sha(FROZEN_ABI):
        raise CaseError('Corpus does not target the frozen treasury v0 ABI')
    if not 1 <= len(data['state']) <= 16:
        raise CaseError('1-16 state fields')
    ids = set()
    for scenario in data['scenarios']:
        if not 1 <= len(scenario['steps']) <= 64 or scenario['id'] in ids:
            raise CaseError(f'Scenario {scenario.get("id")}: 1-64 steps and a unique id')
        ids.add(scenario['id'])
        t = 0
        for step in scenario['steps']:
            t += int(step['advance'])
            if step['t'] != t or step['scope'] not in ('strict', 'rejection') or \
                    not re.fullmatch(r'(0|[1-9][0-9]*)', step['value']):
                raise CaseError(f'{step.get("id")}: inconsistent schedule, scope, or value')
            t += 1
    return data


def resolve(value, roles, t0):
    if isinstance(value, dict):
        if 'role' in value:
            return roles[value['role']]
        if 't' in value:
            return str(t0 + value['t'])
        if 'selector' in value:
            return cast('sig', value['selector']).lower()
    if isinstance(value, list):
        return '(' + ','.join(resolve(v, roles, t0) for v in value) + ')'
    return MAX if value == 'MAX' else value


def interface(stamp):
    abis = [json.loads(FROZEN_ABI.read_text())] + [
        json.loads((BUILD / stamp['targets'][t]['abi']).read_text()) for t in HARNESS.values()]
    events = {}
    for abi in abis:
        for e in abi:
            if e['type'] == 'event':
                events[e['name']] = e
    return abis, events


def expected_observation(step, roles, t0, events):
    """The spec's outcome for one step, encoded with cast (independent of both compilers)."""
    e = step['expect']
    if 'reject' in e:
        return {'success': False, 'returndata': '0x', 'logs': []}
    if 'error' in e:
        return {'success': False, 'logs': [],
                'returndata': cast('calldata', e['error'], *(resolve(a, roles, t0) for a in e['args'])).lower()}
    types, values = e['ok']['types'], e['ok']['values']
    returndata = cast('abi-encode', f'f({",".join(types)})', *(resolve(v, roles, t0) for v in values)).lower() \
        if types else '0x'
    logs = []
    for item in e['events']:
        entry = events[item['event']]
        inputs = entry['inputs']
        signature = f'{entry["name"]}({",".join(i["type"] for i in inputs)})'
        values = [resolve(v, roles, t0) for v in item['args']]
        topics = [cast('sig-event', signature).lower()] + [
            cast('abi-encode', f'f({i["type"]})', v).lower() for i, v in zip(inputs, values) if i['indexed']]
        data_types = [i['type'] for i, v in zip(inputs, values) if not i['indexed']]
        data_values = [v for i, v in zip(inputs, values) if not i['indexed']]
        data = cast('abi-encode', f'f({",".join(data_types)})', *data_values).lower() if data_types else '0x'
        logs.append({'address': roles[item['emitter']], 'topics': topics, 'data': data})
    return {'success': True, 'returndata': returndata, 'logs': logs}


def state_entries(corpus, scenario):
    out = []
    for entry in corpus['state']:
        entry = dict(entry)
        if entry.get('balance') == 'payee':
            entry['balance'] = scenario['payee']
        out.append(entry)
    return out


def run_scenario(stamp, target, corpus, scenario, events):
    identity = stamp['targets'][target]
    creation = lambda t: '0x' + (BUILD / stamp['targets'][t]['creation']).read_text().strip().removeprefix('0x')
    with World(deployer=0, caller=1, accounts=corpus['actors']) as world:
        args = cast('abi-encode', 'f(address)', *(resolve(a, world.roles, 0) for a in
                                                  corpus['deployment']['treasury_args']))
        deployment = world.deploy(creation(target), args)
        steps, expected = [], []
        if deployment['success']:
            for name in corpus['deployment']['aux_order']:
                if name in scenario['aux']:
                    aux_args = ''
                    if name == 'reentrant':
                        aux_args = cast('abi-encode', 'f(address,uint256)',
                                        *(resolve(a, world.roles, 0) for a in corpus['deployment']['reentrant_args']))
                    aux = world.deploy(creation(HARNESS[name]), aux_args, name=name)
                    if not aux['success']:
                        raise InfrastructureError(f'Harness {name} failed to deploy')
            t0 = world.clock + 1
            state = state_entries(corpus, scenario)
            for step in scenario['steps']:
                world.advance(int(step['advance']))
                data = step.get('calldata') or cast('calldata', step['call'],
                                                    *(resolve(a, world.roles, t0) for a in step['args'])).lower()
                observation = world.call(data, sender_role=step['from'], state=state, to_role=step['to'],
                                         value=int(step['value']))
                if observation['timestamp'] != t0 + step['t']:
                    raise InfrastructureError(f'{step["id"]}: mined at an unexpected timestamp')
                steps.append({'id': step['id'], 'call': step.get('call') or f'calldata {data}',
                              'argument': json.dumps(step.get('args', [])), 'from': step['from'],
                              'calldata': data, **observation})
                expected.append(expected_observation(step, world.roles, t0, events))
        return {'format': 'fe-compatibility-raw-execution', 'version': 2, 'implementation': target,
                'scenario': scenario['id'], 'target': identity, 'tools': world.versions, 'world': dict(world.roles),
                'environment': {'hardfork': 'osaka', 'chain_id': 31337, 'base_fee': 0, 'gas_limit_per_tx': 2_000_000,
                                'gas_price': 1, 'mining': 'one mined transaction per block, scheduled timestamps'},
                'deployment': deployment, 'steps': steps}, expected


def spec_check(scenario, record, expected):
    """Fe compares the spec outcome (status, exact returndata, exact events) with one implementation."""
    steps = [(STRICT, s['scope'] == 'strict', e, {**o, 'state': []})
             for s, e, o in zip(scenario['steps'], expected, record['steps'])]
    decision = fecheck.sequence(EXPECTED_DEPLOYMENT, record['deployment'], steps)
    for m in decision['mismatches']:
        m['action'] = scenario['steps'][m['step']]['id']
    return decision


def differential(scenario, left, right):
    if len(left['steps']) != len(right['steps']):
        raise InfrastructureError('Different step counts')
    return fecheck.sequence(left['deployment'], right['deployment'],
                            [(STRICT, s['scope'] == 'strict', a, b)
                             for s, a, b in zip(scenario['steps'], left['steps'], right['steps'])])


def state_decls(corpus, scenario):
    return [(e['name'], f'{e["getter"]}{e["args"]} word {e["word"]}' if 'getter' in e else
             f'balance of {e["balance"]}', e['kind']) for e in state_entries(corpus, scenario)]


def run(left, right, only=None, record_dir=None, corpus_path=CORPUS, extra_targets=None):
    """extra_targets: additional target identities (paths relative to .tools/build), e.g. a tester's port."""
    corpus = load(corpus_path)
    stamp = load_stamp()
    stamp['targets'].update(extra_targets or {})
    abis, events = interface(stamp)
    scenarios = [s for s in corpus['scenarios'] if only is None or s['id'] in only]
    jobs = [(t, s) for s in scenarios for t in dict.fromkeys((left, right))]
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda j: run_scenario(stamp, j[0], corpus, j[1], events), jobs))
    results = {(t, s['id']): o for (t, s), o in zip(jobs, outcomes)}
    out = {'format': 'fe-compatibility-treasury-run-v1', 'corpus_sha256': sha(corpus_path), 'left': left, 'right': right,
           'scenarios': {}}
    face = reporting.Interface(*abis, json.loads((BUILD / stamp['targets'][right]['abi']).read_text()))
    for s in scenarios:
        (lrec, lexp), (rrec, rexp) = results[(left, s['id'])], results[(right, s['id'])]
        decision = differential(s, lrec, rrec)
        labels = [{'call': st['call'], 'argument': st['argument'], 'id': st['id'], 'from': st['from']}
                  for st in lrec['steps']]
        out['scenarios'][s['id']] = {
            'spec_oracle': {'left': spec_check(s, lrec, lexp), 'right': spec_check(s, rrec, rexp)},
            'report': reporting.build(f'treasury-v0/{s["id"]} ({len(s["steps"])} actions)',
                                      'behavioral conformance (strict; compiler rejections by status)',
                                      lrec, rrec, decision, face, state_decls(corpus, s), labels)}
        if record_dir:
            record_dir.mkdir(parents=True, exist_ok=True)
            for rec in (lrec, rrec):
                (record_dir / f'raw-{rec["implementation"]}-{s["id"]}.json').write_text(json.dumps(rec, indent=2) + '\n')
    out['summary'] = {
        'actions': sum(len(s['steps']) for s in scenarios),
        'spec_oracle_left': all(v['spec_oracle']['left']['verdict'] == 'match' for v in out['scenarios'].values()),
        'spec_oracle_right': all(v['spec_oracle']['right']['verdict'] == 'match' for v in out['scenarios'].values()),
        'differential_match': all(v['report']['decision']['verdict'] == 'match' for v in out['scenarios'].values()),
        'first_divergence': {sid: (v['report']['mismatches'][0]['step'], v['report']['mismatches'][0]['category'])
                             for sid, v in out['scenarios'].items() if v['report']['mismatches']},
    }
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--left', default='solidity-treasury')
    parser.add_argument('--right', default='fe-treasury')
    parser.add_argument('--scenario', action='append')
    parser.add_argument('--record-dir', type=Path)
    args = parser.parse_args()
    try:
        out = run(args.left, args.right, args.scenario, args.record_dir)
    except CaseError as error:
        print(json.dumps({'verdict': 'invalid', 'error': str(error)}, indent=2))
        return 2
    except (InfrastructureError, RpcError, OSError, KeyError) as error:
        print(json.dumps({'verdict': 'infrastructure', 'error': f'{type(error).__name__}: {error}'}, indent=2))
        return 3
    print(json.dumps(out, indent=2, sort_keys=True))
    s = out['summary']
    return 0 if s['spec_oracle_left'] and s['spec_oracle_right'] and s['differential_match'] else 1


if __name__ == '__main__':
    sys.exit(main())
