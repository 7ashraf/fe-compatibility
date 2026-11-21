#!/usr/bin/env python3
"""Phase 1 ABI conformance: run the Codec v1 golden vectors against both implementations.

Fe makes every decision:
  * classify each vector's calldata (and golden returndata) with the ABI validator;
  * compare each implementation's observations with the golden bytes;
  * compare the two implementations with each other, raw and across differently
    addressed worlds using the allowlisted normalization;
  * report a failed deployment as not comparable.

Python loads and validates the fixture, drives the chains, and moves bytes.

Exit status: 0 every expectation held, 1 a conformance expectation failed,
2 invalid fixture, 3 infrastructure error.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import ROOT, BUILD, InfrastructureError, load_stamp, sha  # noqa: E402
from evm_chain import RpcError, cast  # noqa: E402
import fecheck  # noqa: E402
from world import World  # noqa: E402

FIXTURE = ROOT / 'fixtures/abi/codec-v1.json'
ABI = ROOT / 'spec/codec-v1.abi.json'
TOP = {'format', 'schema_version', 'fixture', 'interface_sha256', 'reference_world', 'constructor', 'vectors',
       'deployment_vectors', 'provenance'}
CATEGORIES = {'canonical', 'selector', 'truncated', 'extra', 'type', 'offset', 'length', 'padding'}
ROLE_IDS = {'deployer': 1, 'caller': 2, 'target': 3}
# Events each function may emit (spec/codec-v1.md); Echoed's indexed sender (topic 1) is an address.
EMITS = {'echo(bytes)': [[0, 1]]}
HEX = re.compile(r'0x([0-9a-f]{2})*')
QUANTITY = re.compile(r'-?(0|[1-9][0-9]*)')


class CaseError(ValueError):
    pass


def canonical_abi(entries):
    def t(x):
        return '(' + ','.join(t(c) for c in x['components']) + ')' if x['type'] == 'tuple' else x['type']
    return sorted(json.dumps([e['type'], e.get('name'), [[t(x), bool(x.get('indexed'))] for x in e.get('inputs', [])],
                              [t(o) for o in e.get('outputs', [])], e.get('stateMutability'), e.get('anonymous')])
                  for e in entries)


def functions(entries):
    out = {}
    for e in entries:
        if e['type'] == 'function':
            def t(x):
                return '(' + ','.join(t(c) for c in x['components']) + ')' if x['type'] == 'tuple' else x['type']
            inputs = [t(x) for x in e['inputs']]
            out[f'{e["name"]}({",".join(inputs)})'] = (inputs, [t(o) for o in e['outputs']])
    return out


def check_hex(value, name, limit=256):
    if not isinstance(value, str) or not HEX.fullmatch(value) or (len(value) - 2) // 2 > limit:
        raise CaseError(f'{name}: expected lowercase 0x hex of at most {limit} bytes')


def check_value(value, name):
    """Arguments are strings, {"role": r}, {"role_word": r}, or lists (tuples). Never JSON numbers."""
    if isinstance(value, bool) or isinstance(value, (int, float)) or value is None:
        raise CaseError(f'{name}: JSON numbers, booleans and null are not allowed; use decimal strings')
    if isinstance(value, list):
        for i, v in enumerate(value):
            check_value(v, f'{name}[{i}]')
    elif isinstance(value, dict):
        if len(value) != 1 or next(iter(value)) not in ('role', 'role_word') or \
                value.get('role', value.get('role_word')) not in ('deployer', 'caller', 'target', 'zero'):
            raise CaseError(f'{name}: unknown role reference')
    elif not isinstance(value, str) or len(value) > 256 or not (
            QUANTITY.fullmatch(value) or HEX.fullmatch(value) or value in ('true', 'false')):
        raise CaseError(f'{name}: expected a canonical decimal string, 0x hex, or true/false')


def exact_keys(obj, keys, name, optional=()):
    if not isinstance(obj, dict) or not set(keys) <= set(obj) or not set(obj) <= set(keys) | set(optional):
        raise CaseError(f'{name}: expected exactly {sorted(keys)}')


def address_words(types):
    words, index = [], 0
    for t in types:
        for x in (t[1:-1].split(',') if t.startswith('(') else [t]):
            if x == 'address':
                words.append(index)
            index += 1
    return words


def load(path):
    try:
        return _load(path)
    except CaseError:
        raise
    except OSError as error:
        raise CaseError(f'Cannot read fixture: {error.strerror}') from error
    except (KeyError, TypeError, AttributeError, IndexError, ValueError) as error:
        raise CaseError(f'Malformed fixture structure: {type(error).__name__}') from error


def _load(path):
    try:
        raw = path.read_bytes()
        if len(raw) > 262144:
            raise CaseError('Fixture larger than 256 KiB')
        def no_duplicates(pairs):
            keys = [k for k, _ in pairs]
            if len(keys) != len(set(keys)):
                raise CaseError('Duplicate JSON key')
            return dict(pairs)
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=no_duplicates,
                          parse_constant=lambda c: (_ for _ in ()).throw(CaseError('Non-finite number')))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaseError(f'Unreadable fixture: {error}') from error
    exact_keys(data, TOP, 'fixture')
    if data['format'] != 'fe-compatibility-abi-vectors' or type(data['schema_version']) is not int \
            or data['schema_version'] != 1:
        raise CaseError('Unsupported format or schema_version (expected fe-compatibility-abi-vectors v1)')
    if data['fixture'] != 'codec-v1' or data['interface_sha256'] != sha(ABI):
        raise CaseError('Fixture does not target the frozen spec/codec-v1.abi.json')
    frozen = functions(json.loads(ABI.read_text()))
    roles = data['reference_world'].get('roles', {}) if isinstance(data['reference_world'], dict) else {}
    if set(roles) != {'deployer', 'caller', 'target', 'zero'}:
        raise CaseError('reference_world.roles must name deployer, caller, target, zero')
    for r, a in roles.items():
        if not isinstance(a, str) or not re.fullmatch(r'0x[0-9a-f]{40}', a):
            raise CaseError(f'reference_world.roles.{r}: expected a lowercase address')
    exact_keys(data['constructor'], {'types', 'args', 'encoded'}, 'constructor')
    check_value(data['constructor']['args'], 'constructor.args')
    check_hex(data['constructor']['encoded'], 'constructor.encoded')
    vectors = data['vectors']
    if not isinstance(vectors, list) or not 1 <= len(vectors) <= 64:
        raise CaseError('vectors: 1-64 entries')
    seen = set()
    for v in vectors:
        name = f'vector {v.get("id") if isinstance(v, dict) else "?"}'
        common = {'id', 'kind', 'signature', 'inputs', 'outputs', 'args', 'calldata', 'calldata_category',
                  'calldata_index', 'normalize'}
        if not isinstance(v, dict) or v.get('kind') not in ('valid', 'malformed'):
            raise CaseError(f'{name}: kind must be valid or malformed')
        if v['kind'] == 'valid':
            exact_keys(v, common | {'expected'}, name, optional={'note'})
        else:
            exact_keys(v, common | {'expected_outcome', 'edit'}, name)
        if not isinstance(v['id'], str) or not re.fullmatch(r'[a-z0-9-]{1,64}', v['id']) or v['id'] in seen:
            raise CaseError(f'{name}: id must be unique [a-z0-9-]{{1,64}}')
        seen.add(v['id'])
        if v['signature'] not in frozen or frozen[v['signature']] != (v['inputs'], v['outputs']):
            raise CaseError(f'{name}: signature/inputs/outputs differ from the frozen ABI')
        check_value(v['args'], f'{name}.args')
        check_hex(v['calldata'], f'{name}.calldata')
        if v['calldata_category'] not in CATEGORIES or type(v['calldata_index']) is not int \
                or not 0 <= v['calldata_index'] < 8:
            raise CaseError(f'{name}: bad calldata_category/calldata_index')
        if v['kind'] == 'valid':
            e = v['expected']
            exact_keys(e, {'success', 'returndata', 'logs'}, f'{name}.expected')
            if type(e['success']) is not bool or not isinstance(e['logs'], list) or len(e['logs']) > 4:
                raise CaseError(f'{name}.expected: success must be a boolean and logs at most 4')
            check_hex(e['returndata'], f'{name}.expected.returndata')
            for i, log in enumerate(e['logs']):
                exact_keys(log, {'emitter', 'topics', 'data'}, f'{name}.expected.logs[{i}]')
                if not isinstance(log['topics'], list) or len(log['topics']) > 4:
                    raise CaseError(f'{name}: at most 4 topics')
                for t in log['topics']:
                    check_hex(t, f'{name}.topic', limit=32)
                    if len(t) != 66:
                        raise CaseError(f'{name}: topics are exactly 32 bytes')
                check_hex(log['data'], f'{name}.log.data')
                check_hex(log['emitter'], f'{name}.log.emitter', limit=20)
        elif v['expected_outcome'] not in ('reject', 'unspecified') or not isinstance(v['edit'], str):
            raise CaseError(f'{name}: expected_outcome must be reject or unspecified')
        derived = {'return_words': address_words(v['outputs']), 'topics': EMITS.get(v['signature'], []),
                   'data_words': []}
        if v['normalize'] != derived:
            raise CaseError(f'{name}: normalize differs from the allowlist derived from the frozen ABI')
    if not isinstance(data['deployment_vectors'], list) or len(data['deployment_vectors']) != 1:
        raise CaseError('deployment_vectors: exactly one entry in schema v1')
    for d in data['deployment_vectors']:
        exact_keys(d, {'id', 'args', 'encoded', 'expected_success', 'expected_revert'}, 'deployment vector')
        check_value(d['args'], 'deployment.args')
        check_hex(d['encoded'], 'deployment.encoded')
        check_hex(d['expected_revert'], 'deployment.expected_revert')
    return data


def resolve(value, roles):
    if isinstance(value, dict):
        role = value.get('role', value.get('role_word'))
        return roles[role] if 'role' in value else '0x' + roles[role][2:].rjust(64, '0')
    if isinstance(value, list):
        return '(' + ','.join(resolve(v, roles) for v in value) + ')'
    return value


def calldata_for(vector, roles):
    """Valid vectors are re-encoded (by cast) for a world's roles; malformed bytes are fixed."""
    if vector['kind'] == 'malformed':
        return vector['calldata']
    return cast('calldata', vector['signature'], *(resolve(a, roles) for a in vector['args'])).lower()


def run_world(stamp, target, fixture, deployer=0, caller=1, constructor_args=None):
    identity = stamp['targets'][target]
    creation = '0x' + (BUILD / identity['creation']).read_text().strip().removeprefix('0x')
    with World(deployer=deployer, caller=caller) as world:
        args = constructor_args if constructor_args is not None else fixture['constructor']['args']
        encoded = cast('abi-encode', 'f(address)', *(resolve(a, world.roles) for a in args))
        deployment = world.deploy(creation, encoded)
        steps = []
        if deployment['success']:
            reference = world.roles == fixture['reference_world']['roles']
            for v in fixture['vectors']:
                data = calldata_for(v, world.roles)
                if reference and data != v['calldata']:
                    raise InfrastructureError(f'{v["id"]}: re-encoded calldata differs from the golden calldata')
                observation = world.call(data)
                steps.append({'id': v['id'], 'calldata': data, **observation})
        return {'format': 'fe-compatibility-raw-execution', 'version': 2, 'implementation': target,
                'target': identity, 'tools': world.versions, 'world': dict(world.roles),
                'deployment': deployment, 'steps': steps}


EXPECTED_DEPLOYMENT = {'success': True, 'checker_returndata': '0x', 'logs': []}


def golden(fixture, record):
    """Fe compares one implementation's observations with the golden vectors."""
    steps = []
    for v, observed in zip(fixture['vectors'], record['steps']):
        if v['kind'] == 'valid':
            e = v['expected']
            expected = {'success': e['success'], 'returndata': e['returndata'],
                        'logs': [{'address': l['emitter'], 'topics': l['topics'], 'data': l['data']} for l in e['logs']]}
            steps.append(({}, True, expected, observed))
        elif v['expected_outcome'] == 'reject':
            steps.append(({}, False, {'success': False, 'returndata': '0x', 'logs': []}, observed))
    ids = [v['id'] for v in fixture['vectors'] if v['kind'] == 'valid' or v['expected_outcome'] == 'reject']
    decision = fecheck.sequence(EXPECTED_DEPLOYMENT, record['deployment'], steps)
    if 'first_divergence' in decision:
        decision['first_divergence']['vector'] = ids[decision['first_divergence']['step']]
    return decision


def differential(fixture, left, right, normalize=True, only=None):
    """Fe compares two implementations. Malformed vectors use the rejection scope."""
    vectors = [v for v in fixture['vectors'] if only is None or v['id'] in only]
    by_id = {s['id']: s for s in left['steps']}, {s['id']: s for s in right['steps']}
    steps = [((v['normalize'] if normalize else {}), v['kind'] == 'valid',
              by_id[0][v['id']], by_id[1][v['id']]) for v in vectors]
    tables = [{left['world'][r]: i for r, i in ROLE_IDS.items() if r in left['world']},
              {right['world'][r]: i for r, i in ROLE_IDS.items() if r in right['world']}] if normalize else [{}, {}]
    decision = fecheck.sequence(left['deployment'], right['deployment'], steps, *tables)
    if 'first_divergence' in decision:
        decision['first_divergence']['vector'] = vectors[decision['first_divergence']['step']]['id']
    return decision


def classify(fixture):
    """Fe classifies every vector's calldata, and every golden returndata or revert payload."""
    rows = []
    for v in fixture['vectors']:
        selector = cast('sig', v['signature']).lower()
        got = fecheck.validate_abi(v['calldata'], v['inputs'], selector)
        row = {'id': v['id'], 'calldata': got, 'declared': {'category': v['calldata_category'],
                                                              'index': v['calldata_index']}}
        if v['kind'] == 'valid':
            e = v['expected']
            row['golden_returndata'] = (fecheck.validate_abi(e['returndata'], v['outputs']) if e['success'] else
                                        fecheck.validate_abi(e['returndata'], ['uint256', 'uint256'],
                                                             cast('sig', 'TooLong(uint256,uint256)').lower()))
        rows.append(row)
    return rows


def returndata_canonical(fixture, record):
    rows = []
    for v, s in zip(fixture['vectors'], record['steps']):
        if v['kind'] == 'valid' and s['success']:
            rows.append({'id': v['id'], **fecheck.validate_abi(s['returndata'], v['outputs'])})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--fixture', type=Path, default=FIXTURE)
    parser.add_argument('--record-dir', type=Path)
    args = parser.parse_args()
    try:
        fixture = load(args.fixture)
    except CaseError as error:
        print(json.dumps({'verdict': 'invalid', 'error': str(error)}, indent=2))
        return 2
    try:
        stamp = load_stamp()
        frozen = canonical_abi(json.loads(ABI.read_text()))
        abis = {t: canonical_abi(json.loads((BUILD / stamp['targets'][t]['abi']).read_text()))
                for t in ('solidity-codec', 'fe-codec')}
        report = {'format': 'fe-compatibility-phase1-report-v1', 'mode': 'ABI conformance',
                  'fixture': str(args.fixture.relative_to(ROOT)) if args.fixture.is_relative_to(ROOT) else str(args.fixture),
                  'fixture_sha256': sha(args.fixture),
                  'declared_abi_matches_frozen': {t: a == frozen for t, a in abis.items()},
                  'classification': classify(fixture)}
        sol = run_world(stamp, 'solidity-codec', fixture)
        fe = run_world(stamp, 'fe-codec', fixture)
        fe_b = run_world(stamp, 'fe-codec', fixture, deployer=2, caller=3)
        report['golden'] = {'solidity': golden(fixture, sol), 'fe': golden(fixture, fe)}
        report['returndata_canonical'] = {'solidity': returndata_canonical(fixture, sol),
                                          'fe': returndata_canonical(fixture, fe)}
        report['differential'] = differential(fixture, sol, fe, normalize=False)
        control = {'echo-address-bytes'}
        others = {v['id'] for v in fixture['vectors'] if v['id'] not in control}
        report['normalized'] = {
            'worlds': {'left': sol['world'], 'right': fe_b['world']},
            'with_allowlist': differential(fixture, sol, fe_b, normalize=True, only=others),
            'without_normalization': differential(fixture, sol, fe_b, normalize=False, only=others),
            'control_bytes_not_rewritten': differential(fixture, sol, fe_b, normalize=True, only=control)}
        bad = [{'role': 'zero'}]
        failed = {t: run_world(stamp, t, fixture, constructor_args=bad) for t in ('solidity-codec', 'fe-codec')}
        expected_revert = fixture['deployment_vectors'][0]['expected_revert']
        report['deployment'] = {
            'revert_bytes': {t: r['deployment']['returndata'] for t, r in failed.items()},
            'revert_bytes_equal_expected': {t: r['deployment']['returndata'] == expected_revert for t, r in failed.items()},
            'differential': fecheck.sequence(failed['solidity-codec']['deployment'], failed['fe-codec']['deployment'], []),
            # A harness that mistook the constructor revert for a call result would "pass" this step:
            'as_expected_application_revert': fecheck.sequence(
                EXPECTED_DEPLOYMENT, failed['fe-codec']['deployment'],
                [({}, True, {'success': False, 'returndata': expected_revert, 'logs': []},
                  {**failed['fe-codec']['deployment'], 'returndata': failed['fe-codec']['deployment']['returndata']})])}
        report['records'] = {'solidity': sol, 'fe': fe, 'fe-world-b': fe_b, **{f'{t}-zero-owner': r for t, r in failed.items()}}
        if args.record_dir:
            args.record_dir.mkdir(parents=True, exist_ok=True)
            for name, record in report['records'].items():
                (args.record_dir / f'raw-{name}.json').write_text(json.dumps(record, indent=2) + '\n')
        records = report.pop('records')
        ok = expectations(fixture, report)
        report['expectations'] = ok
        print(json.dumps(report, indent=2))
        report['records'] = records
        main.report = report
        return 0 if all(ok.values()) else 1
    except (InfrastructureError, RpcError, OSError) as error:
        print(json.dumps({'verdict': 'infrastructure', 'error': str(error)}, indent=2))
        return 3


def expectations(fixture, r):
    classified = all(c['calldata'] == c['declared'] and c.get('golden_returndata', {'category': 'canonical'})
                     ['category'] == 'canonical' for c in r['classification'])
    unspecified = {v['id'] for v in fixture['vectors'] if v.get('expected_outcome') == 'unspecified'}
    diff = r['differential']
    n = r['normalized']
    return {
        'declared_abis_match_frozen': all(r['declared_abi_matches_frozen'].values()),
        'fe_classifies_every_vector_as_declared': classified,
        'solidity_matches_golden': r['golden']['solidity']['verdict'] == 'match',
        'fe_matches_golden': r['golden']['fe']['verdict'] == 'match',
        'observed_returndata_canonical': all(x['category'] == 'canonical' for side in r['returndata_canonical'].values()
                                             for x in side),
        'differential_match_or_only_unspecified_divergence': diff['verdict'] == 'match' or (
            diff['verdict'] == 'mismatch' and diff['first_divergence']['vector'] in unspecified),
        'normalized_worlds_match': n['with_allowlist']['verdict'] == 'match',
        'unnormalized_worlds_differ': n['without_normalization']['verdict'] == 'mismatch',
        'bytes_content_never_normalized': n['control_bytes_not_rewritten']['verdict'] == 'mismatch'
            and n['control_bytes_not_rewritten']['first_divergence']['category'] == 'returndata-byte',
        'failed_deployment_not_comparable': r['deployment']['differential']['verdict'] == 'not-comparable',
        'constructor_revert_never_passes_as_application_revert':
            r['deployment']['as_expected_application_revert']['verdict'] == 'not-comparable',
    }


if __name__ == '__main__':
    sys.exit(main())
