"""Encode observations for the native Fe checker (protocol 3) and parse its decisions.

Python only serializes bytes here. Every equality, normalization, and ABI
decision is made by the Fe executable.
"""
import re
import subprocess

from common import CHECKER, InfrastructureError

CATEGORIES = {1: 'status', 2: 'returndata-length', 3: 'returndata-byte', 4: 'log-count', 5: 'log-emitter',
              6: 'topic-count', 7: 'topic', 8: 'log-data-length', 9: 'log-data-byte', 10: 'error-selector',
              11: 'error-argument', 12: 'log-missing', 13: 'log-extra', 14: 'log-reordered', 15: 'state-count',
              16: 'state-kind', 17: 'state-value'}
MALFORMATIONS = {0: 'none', 1: 'oversized', 2: 'padding', 3: 'logs-on-revert', 4: 'too-many-logs',
                 5: 'too-many-topics', 6: 'emitter', 7: 'stray-data', 8: 'too-many-state', 9: 'state-value'}
STATE_KINDS = {'uint': 0, 'int': 1, 'address': 2, 'bool': 3, 'word': 4}
VERDICTS = {0: 'match', 1: 'mismatch', 2: 'malformed', 3: 'not-comparable'}
ABI_CATEGORIES = {0: 'canonical', 1: 'selector', 2: 'truncated', 3: 'extra', 4: 'type', 5: 'offset', 6: 'length',
                  7: 'padding', 8: 'bad-layout'}


def payload_words(hex_text):
    raw = bytes.fromhex(hex_text[2:])
    padded = raw + b'\0' * (-len(raw) % 32)
    return [len(raw)] + [int.from_bytes(padded[i:i + 32], 'big') for i in range(0, len(padded), 32)]


def state_word(field):
    value = int(field['value'], 0) if field['value'].startswith('0x') else int(field['value'])
    return value % (1 << 256) if field['kind'] == 'int' else value


def observation_words(observation, returndata_key='returndata'):
    words = [1 if observation['success'] else 0, *payload_words(observation[returndata_key]),
             len(observation['logs'])]
    for log in observation['logs']:
        words += [int(log['address'], 16), len(log['topics']), *(int(t, 16) for t in log['topics']),
                  *payload_words(log['data'])]
    state = observation.get('state', [])
    words.append(len(state))
    for field in state:
        words += [STATE_KINDS[field['kind']], state_word(field)]
    return words


def table_words(table):
    """table: {address hex: role id}."""
    words = [len(table)]
    for address, role in table.items():
        words += [int(address, 16), role]
    return words


def allowlist_words(normalize):
    positions = ([(0, 0, w) for w in normalize.get('return_words', [])]
                 + [(1, l, i) for l, i in normalize.get('topics', [])]
                 + [(2, l, w) for l, w in normalize.get('data_words', [])])
    return [len(positions)] + [n for p in positions for n in p]


def run(words):
    frame = ' '.join(map(str, words))
    try:
        result = subprocess.run([str(CHECKER)], input=frame, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise InfrastructureError(f'Fe checker failed to run: {error}') from error
    if result.returncode != 0:
        raise InfrastructureError(f'Fe checker rejected the frame (exit {result.returncode})')
    reply = result.stdout.split()
    if not reply or not all(re.fullmatch(r'[0-9]+', r) for r in reply):
        raise InfrastructureError(f'Malformed Fe checker reply: {result.stdout!r}')
    return list(map(int, reply)), len(words)


def record(words):
    deployment, step, category, log, index, slot, a, b = words
    return {'deployment': bool(deployment), 'step': step, 'category': CATEGORIES.get(category, 'none'),
            'log': log, 'index': index, 'slot': slot, 'left': str(a), 'right': str(b)}


def sequence(deploy_left, deploy_right, steps, left_table=None, right_table=None, raise_malformed=True):
    """steps: list of (normalize dict, exact_returndata bool, left observation, right observation)."""
    words = [3, 1, *table_words(left_table or {}), *table_words(right_table or {}),
             *observation_words(deploy_left, 'checker_returndata'),
             *observation_words(deploy_right, 'checker_returndata'), len(steps)]
    for normalize, exact, left, right in steps:
        words += [*allowlist_words(normalize), 1 if exact else 0, *observation_words(left), *observation_words(right)]
    reply, size = run(words)
    if len(reply) < 15 or reply[:2] != [3, 1] or reply[2] not in VERDICTS:
        raise InfrastructureError(f'Unexpected Fe checker reply: {reply}')
    verdict, count, total, listed, reason = reply[2:7]
    if len(reply) != 15 + 8 * listed or listed > 8 or count != len(steps) and verdict != 2:
        raise InfrastructureError(f'Inconsistent Fe checker reply: {reply}')
    first = record(reply[7:15])
    decision = {'checker': 'native Fe compat_checker protocol 3', 'frame_words': size,
                'steps_compared': count, 'verdict': VERDICTS[verdict], 'mismatching_steps': total,
                'listed': listed, 'truncated': total > listed,
                'mismatches': [record(reply[15 + 8 * i:23 + 8 * i]) for i in range(listed)]}
    if verdict == 2:
        decision['malformed'] = {'reason': MALFORMATIONS[reason], 'deployment': first['deployment'],
                                 'step': first['step']}
        if raise_malformed:
            raise InfrastructureError(f'Fe checker: malformed observation ({MALFORMATIONS[reason]}, '
                                      f'deployment={first["deployment"]}, step {first["step"]})')
    if verdict == 3:
        decision['deployment_succeeded'] = {'left': first['left'] == '1', 'right': first['right'] == '1'}
    if verdict == 1:
        decision['first_divergence'] = first
    return decision


def layout_words(types):
    words = []
    for t in types:
        if t.startswith('(') and t.endswith(')'):
            inner = t[1:-1].split(',')
            if any(x.startswith('(') or x == 'bytes' for x in inner):
                raise InfrastructureError(f'Unsupported tuple {t}')
            words += layout_words(inner)[1:]
            continue
        match = re.fullmatch(r'(u?int)([0-9]+)', t)
        if match:
            words += [0 if match.group(1) == 'uint' else 1, int(match.group(2))]
        elif t == 'address':
            words += [2, 160]
        elif t == 'bool':
            words += [3, 8]
        elif t == 'bytes':
            words += [4, 0]
        else:
            raise InfrastructureError(f'Unsupported ABI type {t}')
    return [len(words) // 2] + words


def validate_abi(payload_hex, types, selector_hex=None):
    words = [3, 2, *layout_words(types), 1 if selector_hex else 0, int(selector_hex or '0x0', 16),
             *payload_words(payload_hex)]
    reply, _ = run(words)
    if len(reply) != 4 or reply[:2] != [3, 2] or reply[2] not in ABI_CATEGORIES:
        raise InfrastructureError(f'Unexpected Fe ABI reply: {reply}')
    return {'category': ABI_CATEGORIES[reply[2]], 'index': reply[3]}
