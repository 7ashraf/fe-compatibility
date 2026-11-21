#!/usr/bin/env python3
"""Generate fixtures/abi/codec-v1.json, the golden ABI vectors for spec/codec-v1.md.

All encodings come from the pinned `cast` (Foundry 1.5.1, the alloy ABI encoder).
That encoder is independent of both compilers under test (solc and Fe), so
neither implementation is its own oracle. Expected values are written down
from the specification, not by running either contract. Malformed calldata is
built by explicit byte edits of a valid encoding, each documented in the vector.

  python3 scripts/make-vectors.py            # rewrite the fixture
  python3 scripts/make-vectors.py --check    # fail unless the committed fixture is reproduced exactly
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / 'fixtures/abi/codec-v1.json'
ABI = ROOT / 'spec/codec-v1.abi.json'
# Reference world: Anvil default accounts 0 and 1; the target is account 0's first contract.
WORLD = {'deployer': '0xf39fd6e51aad88f6f4ce6ab8827279cfffb92266',
         'caller': '0x70997970c51812dc3a010c7d01b50e0d17dc79c8',
         'target': '0x5fbdb2315678afecb367f032d93f642f64180aa3',
         'zero': '0x0000000000000000000000000000000000000000'}
MAX_ADDRESS = '0x' + 'ff' * 20
ECHOED = 'Echoed(address,uint256)'


def cast(*args):
    return subprocess.check_output(['cast', *map(str, args)], text=True).strip()


def resolve(value, world):
    if isinstance(value, dict) and set(value) == {'role'}:
        return world[value['role']]
    if isinstance(value, dict) and set(value) == {'role_word'}:
        return '0x' + world[value['role_word']][2:].rjust(64, '0')
    if isinstance(value, list):
        return '(' + ','.join(resolve(v, world) for v in value) + ')'
    return value


def encode_call(signature, args, world):
    return cast('calldata', signature, *(resolve(a, world) for a in args)).lower()


def encode_values(types, values, world):
    return cast('abi-encode', f'f({",".join(types)})', *(resolve(v, world) for v in values)).lower()


def address_words(types):
    """Head word indices of address-typed outputs (static tuples flattened)."""
    words, index = [], 0
    for t in types:
        inner = t[1:-1].split(',') if t.startswith('(') else [t]
        for x in inner:
            if x == 'address':
                words.append(index)
            index += 1
    return words


# Events each function may emit, from spec/codec-v1.md; Echoed's indexed `sender` is an address.
EMITS = {'echo(bytes)': [[0, 1]]}


def allowlist(signature, outputs):
    """Normalization positions for a function, from its declared types alone (not its outcome)."""
    return {'return_words': address_words(outputs), 'topics': EMITS.get(signature, []), 'data_words': []}


def echoed(length, world):
    return {'emitter': {'role': 'target'},
            'topics': [cast('sig-event', ECHOED).lower(), '0x' + world['caller'][2:].rjust(64, '0')],
            'data': encode_values(['uint256'], [str(length)], world)}


def concrete_logs(logs, world):
    return [{'emitter': resolve(l['emitter'], world), 'topics': l['topics'], 'data': l['data']} for l in logs]


SIG = {'statics': ('statics(uint8,int16,address,bool)', ['uint8', 'int16', 'address', 'bool'],
                   ['uint8', 'int16', 'address', 'bool']),
       'wide': ('wide(uint256,int256)', ['uint256', 'int256'], ['uint256', 'int256']),
       'point': ('point((uint64,address))', ['(uint64,address)'], ['address', 'uint256']),
       'echo': ('echo(bytes)', ['bytes'], ['bytes']),
       'owner': ('owner()', [], ['address'])}


def valid(vector_id, name, args, returns, logs=(), revert=None, note=None):
    signature, inputs, outputs = SIG[name]
    calldata = encode_call(signature, args, WORLD)
    if revert is not None:
        expected = {'success': False, 'returndata': revert, 'logs': []}
    else:
        expected = {'success': True, 'returndata': encode_values(outputs, returns, WORLD),
                    'logs': concrete_logs(list(logs), WORLD)}
    vector = {'id': vector_id, 'kind': 'valid', 'signature': signature, 'inputs': inputs, 'outputs': outputs,
              'args': args, 'calldata': calldata, 'calldata_category': 'canonical', 'calldata_index': 0,
              'expected': expected, 'normalize': allowlist(signature, outputs)}
    if note:
        vector['note'] = note
    return vector


def malformed(vector_id, name, calldata, category, index, outcome, edit):
    signature, inputs, outputs = SIG[name]
    return {'id': vector_id, 'kind': 'malformed', 'signature': signature, 'inputs': inputs, 'outputs': outputs,
            'args': [], 'calldata': calldata, 'calldata_category': category, 'calldata_index': index,
            'expected_outcome': outcome, 'edit': edit, 'normalize': allowlist(signature, outputs)}


def word_edit(calldata, word, new_word_hex):
    raw = calldata[2:]
    start = 8 + 64 * word
    return '0x' + raw[:start] + new_word_hex.rjust(64, '0') + raw[start + 64:]


def build():
    w = WORLD
    payload64 = '0x' + ''.join(f'{i:02x}' for i in range(1, 65))
    payload65 = payload64 + '41'
    vectors = [
        valid('statics-zero', 'statics', ['0', '0', {'role': 'zero'}, 'false'], ['0', '0', w['zero'], 'false']),
        valid('statics-max', 'statics', ['255', '32767', {'role': 'caller'}, 'true'], ['255', '32767', w['caller'], 'true']),
        valid('statics-min', 'statics', ['1', '-32768', MAX_ADDRESS, 'false'], ['1', '-32768', MAX_ADDRESS, 'false']),
        valid('statics-minus-one', 'statics', ['0', '-1', {'role': 'deployer'}, 'true'],
              ['0', '-1', w['deployer'], 'true']),
        valid('wide-max', 'wide', [str(2**256 - 1), str(2**255 - 1)], [str(2**256 - 1), str(2**255 - 1)]),
        valid('wide-min', 'wide', ['0', str(-2**255)], ['0', str(-2**255)]),
        valid('wide-beyond-double', 'wide', ['9007199254740993', '-9007199254740993'],
              ['9007199254740993', '-9007199254740993'], note='2^53 + 1: not representable as an IEEE double'),
        valid('point-max', 'point', [[str(2**64 - 1), {'role': 'deployer'}]], [w['deployer'], str(2**64 - 1)]),
        valid('point-beyond-double', 'point', [['9007199254740993', {'role': 'zero'}]], [w['zero'], '9007199254740993']),
        valid('echo-empty', 'echo', ['0x'], ['0x'], logs=[echoed(0, w)]),
        valid('echo-leading-zero', 'echo', ['0x00'], ['0x00'], logs=[echoed(1, w)]),
        valid('echo-address-bytes', 'echo', [{'role_word': 'target'}], [{'role_word': 'target'}], logs=[echoed(32, w)],
              note='Normalization control: the target address inside bytes is never rewritten'),
        valid('echo-max', 'echo', [payload64], [payload64], logs=[echoed(64, w)]),
        valid('echo-too-long', 'echo', [payload65], None, revert=cast('calldata', 'TooLong(uint256,uint256)', 65, 64).lower()),
        valid('owner', 'owner', [], [w['deployer']]),
    ]
    statics = vectors[1]['calldata']
    point = vectors[7]['calldata']
    echo1 = encode_call('echo(bytes)', ['0x01'], w)
    selector = statics[:10]
    vectors += [
        malformed('m-unknown-selector', 'statics', '0xdeadbeef' + statics[10:], 'selector', 0, 'reject',
                  'statics-max with selector replaced by 0xdeadbeef'),
        malformed('m-empty', 'statics', '0x', 'truncated', 0, 'reject', 'empty calldata'),
        malformed('m-truncated-word', 'statics', statics[:-64], 'truncated', 3, 'reject', 'statics-max without its last word'),
        malformed('m-truncated-byte', 'statics', statics[:-2], 'truncated', 3, 'reject', 'statics-max without its last byte'),
        malformed('m-uint8-dirty', 'statics', word_edit(statics, 0, '100'), 'type', 0, 'reject', 'small = 256'),
        malformed('m-int16-unextended', 'statics', word_edit(statics, 1, '8000'), 'type', 1, 'reject',
                  'delta word 0x8000 without sign extension'),
        malformed('m-address-dirty', 'statics', word_edit(statics, 2, '01' + w['caller'][2:]), 'type', 2, 'reject',
                  'who with bit 160 set'),
        malformed('m-bool-two', 'statics', word_edit(statics, 3, '2'), 'type', 3, 'reject', 'flag = 2'),
        malformed('m-uint64-dirty', 'point', word_edit(point, 0, '1' + '0' * 16), 'type', 0, 'reject', 'p.x = 2^64'),
        malformed('m-echo-length-overrun', 'echo', word_edit(echo1, 1, '64'), 'length', 0, 'reject',
                  'echo(0x01) with declared length 100 and one data word'),
        malformed('m-echo-offset-noncanonical', 'echo', '0x' + echo1[2:10] + '40'.rjust(64, '0') + '0' * 64 + echo1[74:],
                  'offset', 0, 'unspecified', 'echo(0x01) with offset 64 and an extra zero word'),
        malformed('m-echo-dirty-padding', 'echo', echo1[:-2] + '01', 'padding', 0, 'unspecified',
                  'echo(0x01) with a nonzero padding byte'),
        malformed('m-statics-trailing', 'statics', statics + '0' * 64, 'extra', 0, 'unspecified',
                  'statics-max with a trailing zero word'),
    ]
    assert selector == '0x4ce65209'
    abi_bytes = ABI.read_bytes()
    return {
        'format': 'fe-compatibility-abi-vectors', 'schema_version': 1, 'fixture': 'codec-v1',
        'interface_sha256': hashlib.sha256(abi_bytes).hexdigest(),
        'reference_world': {'roles': w, 'note': 'Anvil accounts 0 (deployer) and 1 (caller); target = '
                                                'deployer nonce 0'},
        'constructor': {'types': ['address'], 'args': [{'role': 'deployer'}],
                        'encoded': encode_values(['address'], [{'role': 'deployer'}], w)},
        'vectors': vectors,
        'deployment_vectors': [{'id': 'd-zero-owner', 'args': [{'role': 'zero'}],
                                'encoded': encode_values(['address'], [{'role': 'zero'}], w),
                                'expected_success': False,
                                'expected_revert': cast('sig', 'InvalidOwner()').lower()}],
        'provenance': {'generator': 'scripts/make-vectors.py', 'encoder': cast('--version').splitlines()[0],
                       'independence': 'Encoded by cast (alloy), not solc or Fe; expected values written from '
                                       'spec/codec-v1.md, not obtained by running either implementation.'},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if '1.5.1-stable' not in cast('--version'):
        sys.exit('cast is not the pinned Foundry 1.5.1-stable')
    text = json.dumps(build(), indent=2) + '\n'
    if args.check:
        if FIXTURE.read_text() != text:
            sys.exit('fixtures/abi/codec-v1.json is not reproduced by scripts/make-vectors.py')
        print('PASS golden vectors reproduced byte-for-byte')
        return
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(text)
    print(f'Wrote {FIXTURE.relative_to(ROOT)}: {len(json.loads(text)["vectors"])} vectors')


if __name__ == '__main__':
    main()
