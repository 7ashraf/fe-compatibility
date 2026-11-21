#!/usr/bin/env python3
"""Generate fixtures/behavior/treasury-v0.json, the Phase 3 behavioral corpus.

Every expected outcome is written from spec/vendor/treasury-v0/treasury-v0.md
(revision 1): which actions succeed, the exact custom error and its arguments
for each rejection, the return values, and the exact treasury events. None of
it is obtained by running either implementation. The runner encodes the
expectations with `cast` at run time, because addresses and timestamps are
resolved per world.

Value expressions: a decimal string, "MAX" (2^256-1), {"role": name},
{"t": k} (the scenario's first block timestamp plus k), or
{"selector": "Error()"} (4-byte error data).
Each action is mined in its own block, one second after the previous one,
unless it has an `advance`.

  python3 scripts/make-corpus.py [--check]
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'fixtures/behavior/treasury-v0.json'
ABI = ROOT / 'spec/vendor/treasury-v0/treasury-v0.abi.json'

R = lambda role: {'role': role}
T = lambda k: {'t': k}
GRANT = '(bool,address,address,uint256,uint256,uint256,bool)'


class Scenario:
    def __init__(self, sid, description, aux=(), payee='recipient'):
        self.data = {'id': sid, 'description': description, 'aux': list(aux), 'payee': payee, 'steps': []}
        self.t = 0

    def step(self, sender, call, args=(), value='0', ok=None, error=None, error_args=(), events=(), to='target',
             advance=0, calldata=None, reject=False, covers=()):
        self.t += advance
        s = {'id': f'{self.data["id"]}-{len(self.data["steps"])}', 'from': sender, 'to': to, 'value': value,
             't': self.t, 'advance': str(advance), 'covers': list(covers)}
        if calldata is not None:
            s['calldata'] = calldata
        else:
            s['call'], s['args'] = call, list(args)
        if reject:
            s['scope'], s['expect'] = 'rejection', {'reject': True}
        elif error:
            s['scope'], s['expect'] = 'strict', {'error': error, 'args': list(error_args)}
        else:
            s['scope'] = 'strict'
            s['expect'] = {'ok': ok or {'types': [], 'values': []},
                           'events': [{'emitter': e[2] if len(e) > 2 else 'target', 'event': e[0], 'args': list(e[1])}
                                      for e in events]}
        self.data['steps'].append(s)
        self.t += 1
        return self

    def now(self):
        return T(self.t)


def ok(types, *values):
    return {'types': types, 'values': list(values)}


def grant(sc, cap, expiry, sender='owner', delegate=R('delegate'), recipient=R('recipient'), gid='1'):
    return sc.step(sender, 'createGrant(address,address,uint256,uint256)', [delegate, recipient, cap, expiry],
                   ok=ok(['uint256'], gid), events=[('GrantCreated', [gid, delegate, recipient, cap, expiry])])


def spend(sc, gid, amount, new_spent, recipient=R('recipient'), sender='delegate', covers=()):
    return sc.step(sender, 'spend(uint256,uint256)', [gid, amount],
                   events=[('Spent', [gid, R(sender) if sender != 'batcher' else R('batcher'), recipient, amount,
                                      new_spent])], covers=covers)


def deposit(sc, amount, sender='owner'):
    return sc.step(sender, 'deposit()', value=amount,
                   events=[('Deposited', [R(sender), amount])] if amount != '0' else [])


def scenarios():
    out = []
    s = Scenario('deposit-spend', 'Deposits, a grant, spending up to the exact cap, then over it')
    deposit(s, '100')
    deposit(s, '0', sender='outsider')
    grant(s, '50', T(1000))
    spend(s, '1', '20', '20')
    spend(s, '1', '30', '50', covers=['cap boundary: amount equal to remaining succeeds'])
    s.step('delegate', 'spend(uint256,uint256)', ['1', '1'], error='CapExceeded(uint256,uint256)', error_args=['0', '1'])
    s.step('outsider', 'getGrant(uint256)', ['1'],
           ok=ok([GRANT], ['true', R('delegate'), R('recipient'), '50', '50', T(1000), 'true']))
    s.step('outsider', 'nextGrantId()', ok=ok(['uint256'], '2'))
    s.step('outsider', 'treasuryBalance()', ok=ok(['uint256'], '50'))
    s.step('outsider', 'owner()', ok=ok(['address'], R('owner')))
    out.append(s)

    s = Scenario('cap-boundary', 'Cap boundary: one over, exactly remaining, then exhausted; zero amount')
    deposit(s, '100')
    grant(s, '10', T(1000))
    s.step('delegate', 'spend(uint256,uint256)', ['1', '11'], error='CapExceeded(uint256,uint256)',
           error_args=['10', '11'], covers=['cap boundary'])
    spend(s, '1', '10', '10', covers=['cap boundary'])
    s.step('delegate', 'spend(uint256,uint256)', ['1', '1'], error='CapExceeded(uint256,uint256)', error_args=['0', '1'])
    s.step('delegate', 'spend(uint256,uint256)', ['1', '0'], error='InvalidAmount()')
    out.append(s)

    s = Scenario('expiry-equality', 'Spends before expiry, rejection at exactly the expiry second and after')
    deposit(s, '100')
    grant(s, '10', T(4))
    spend(s, '1', '1', '1')
    spend(s, '1', '1', '2')
    s.step('delegate', 'spend(uint256,uint256)', ['1', '1'], error='Expired(uint256,uint256)',
           error_args=[T(4), T(4)], covers=['expiry equality rejects'])
    s.step('delegate', 'spend(uint256,uint256)', ['1', '1'], error='Expired(uint256,uint256)',
           error_args=[T(4), T(105)], advance=100)
    s.step('owner', 'revoke(uint256)', ['1'], events=[('GrantRevoked', ['1'])], covers=['expired grant is revocable'])
    out.append(s)

    s = Scenario('invalid-creation', 'Creation validation order and maximal quantities')
    c = 'createGrant(address,address,uint256,uint256)'
    s.step('owner', c, [R('zero'), R('recipient'), '10', T(100)], error='InvalidAddress()')
    s.step('owner', c, [R('delegate'), R('zero'), '10', T(100)], error='InvalidAddress()')
    s.step('owner', c, [R('delegate'), R('recipient'), '0', T(100)], error='InvalidAmount()')
    s.step('owner', c, [R('delegate'), R('recipient'), '10', T(3)], error='InvalidExpiry()',
           covers=['expiry equal to now is invalid'])
    s.step('owner', c, [R('delegate'), R('recipient'), '10', T(2)], error='InvalidExpiry()')
    s.step('owner', c, [R('zero'), R('recipient'), '0', T(0)], error='InvalidAddress()',
           covers=['address checked before cap and expiry'])
    s.step('outsider', c, [R('zero'), R('zero'), '0', T(0)], error='Unauthorized()',
           covers=['authority checked first'])
    grant(s, 'MAX', 'MAX')
    s.step('outsider', 'nextGrantId()', ok=ok(['uint256'], '2'))
    out.append(s)

    s = Scenario('unauthorized', 'Unauthorized callers, and unknown IDs checked before authority for spend')
    deposit(s, '100')
    grant(s, '10', T(1000))
    for who in ('outsider', 'owner', 'recipient'):
        s.step(who, 'spend(uint256,uint256)', ['1', '1'], error='Unauthorized()', covers=['unauthorized access'])
    s.step('outsider', 'revoke(uint256)', ['1'], error='Unauthorized()')
    s.step('outsider', 'revoke(uint256)', ['99'], error='Unauthorized()', covers=['wrong owner wins over unknown ID'])
    s.step('outsider', 'createGrant(address,address,uint256,uint256)', [R('delegate'), R('recipient'), '10', T(1000)],
           error='Unauthorized()')
    s.step('delegate', 'spend(uint256,uint256)', ['2', '1'], error='UnknownGrant(uint256)', error_args=['2'])
    s.step('outsider', 'spend(uint256,uint256)', ['0', '1'], error='UnknownGrant(uint256)', error_args=['0'],
           covers=['unknown ID checked before authority for spend'])
    s.step('delegate', 'spend(uint256,uint256)', ['MAX', '1'], error='UnknownGrant(uint256)', error_args=['MAX'])
    s.step('outsider', 'getGrant(uint256)', ['MAX'],
           ok=ok([GRANT], ['false', R('zero'), R('zero'), '0', '0', '0', 'false']))
    out.append(s)

    s = Scenario('revocation', 'Revocation, repeated revocation as a silent no-op, and no ID reuse')
    deposit(s, '100')
    grant(s, '10', T(1000))
    spend(s, '1', '3', '3')
    s.step('owner', 'revoke(uint256)', ['1'], events=[('GrantRevoked', ['1'])], covers=['revocation'])
    s.step('owner', 'revoke(uint256)', ['1'], covers=['repeated revocation: success, no event'])
    s.step('delegate', 'spend(uint256,uint256)', ['1', '1'], error='InactiveGrant(uint256)', error_args=['1'])
    s.step('outsider', 'spend(uint256,uint256)', ['1', '1'], error='Unauthorized()',
           covers=['authority checked before active'])
    s.step('owner', 'revoke(uint256)', ['99'], error='UnknownGrant(uint256)', error_args=['99'])
    s.step('owner', 'revoke(uint256)', ['0'], error='UnknownGrant(uint256)', error_args=['0'])
    s.step('outsider', 'getGrant(uint256)', ['1'],
           ok=ok([GRANT], ['true', R('delegate'), R('recipient'), '10', '3', T(1000), 'false']))
    grant(s, '5', T(1000), gid='2')
    spend(s, '2', '5', '5')
    out.append(s)

    s = Scenario('insufficient-funds', 'Grants do not reserve funds: balance checks after cap checks')
    deposit(s, '5')
    grant(s, '50', T(1000))
    s.step('delegate', 'spend(uint256,uint256)', ['1', '10'], error='InsufficientBalance(uint256,uint256)',
           error_args=['5', '10'], covers=['insufficient funds'])
    spend(s, '1', '5', '5')
    s.step('delegate', 'spend(uint256,uint256)', ['1', '1'], error='InsufficientBalance(uint256,uint256)',
           error_args=['0', '1'])
    deposit(s, '7', sender='outsider')
    spend(s, '1', '7', '12')
    out.append(s)

    s = Scenario('recipient-revert', 'A recipient that rejects payment: the whole spend reverts', aux=['rejecting'],
                 payee='rejecting')
    deposit(s, '100')
    grant(s, '10', T(1000), recipient=R('rejecting'))
    s.step('delegate', 'spend(uint256,uint256)', ['1', '4'], error='PaymentFailed()', covers=['recipient revert'])
    s.step('outsider', 'getGrant(uint256)', ['1'],
           ok=ok([GRANT], ['true', R('delegate'), R('rejecting'), '10', '0', T(1000), 'true']))
    s.step('outsider', 'treasuryBalance()', ok=ok(['uint256'], '100'))
    out.append(s)

    s = Scenario('reentry', 'A recipient that re-enters spend() during payment gets Reentrant()', aux=['reentrant'],
                 payee='reentrant')
    deposit(s, '100')
    grant(s, '10', T(1000), recipient=R('reentrant'))
    s.step('delegate', 'spend(uint256,uint256)', ['1', '4'], covers=['reentry blocked; outer spend completes'],
           events=[('Callback', ['false', {'selector': 'Reentrant()'}], 'reentrant'),
                   ('Spent', ['1', R('delegate'), R('reentrant'), '4', '4'])])
    s.step('outsider', 'getGrant(uint256)', ['1'],
           ok=ok([GRANT], ['true', R('delegate'), R('reentrant'), '10', '4', T(1000), 'true']))
    out.append(s)

    s = Scenario('same-transaction', 'Two spends in one transaction both work after unlocking; a bubbled rejection',
                 aux=['batcher'])
    deposit(s, '100')
    grant(s, '10', T(1000), delegate=R('batcher'))
    s.step('outsider', 'twice(address,uint256,uint256)', [R('target'), '1', '4'], to='batcher',
           covers=['second operation in the same transaction works'],
           events=[('Spent', ['1', R('batcher'), R('recipient'), '4', '4']),
                   ('Spent', ['1', R('batcher'), R('recipient'), '4', '8'])])
    s.step('outsider', 'twice(address,uint256,uint256)', [R('target'), '1', '4'], to='batcher',
           error='CapExceeded(uint256,uint256)', error_args=['2', '4'])
    s.step('outsider', 'getGrant(uint256)', ['1'],
           ok=ok([GRANT], ['true', R('batcher'), R('recipient'), '10', '8', T(1000), 'true']))
    out.append(s)

    s = Scenario('dispatch', 'Fallback, payability, and malformed calldata')
    s.step('outsider', None, calldata='0xdeadbeef', error='UnsupportedCall()', covers=['unknown selector'])
    s.step('outsider', None, calldata='0xdead', error='UnsupportedCall()', covers=['short selector'])
    s.step('outsider', None, calldata='0x', error='UnsupportedCall()', covers=['empty calldata, zero value'])
    s.step('outsider', None, calldata='0x', value='1', reject=True, covers=['value to the nonpayable fallback'])
    s.step('owner', 'createGrant(address,address,uint256,uint256)', [R('delegate'), R('recipient'), '10', T(1000)],
           value='1', reject=True, covers=['value to a nonpayable function'])
    deposit(s, '3', sender='outsider')
    s.step('delegate', None, calldata='0xb3a49eae' + '00' * 32, reject=True, covers=['truncated calldata'])
    s.step('outsider', 'spend(uint256,uint256)', ['1', '1'], value='1', reject=True)
    out.append(s)
    return [s.data for s in out]


STATE = [
    {'name': 'nextGrantId', 'kind': 'uint', 'getter': 'nextGrantId()', 'args': [], 'word': 0},
    {'name': 'treasuryBalance', 'kind': 'uint', 'getter': 'treasuryBalance()', 'args': [], 'word': 0},
    *[{'name': f'grant1.{n}', 'kind': k, 'getter': 'getGrant(uint256)', 'args': ['1'], 'word': i}
      for i, (n, k) in enumerate([('exists', 'bool'), ('delegate', 'address'), ('recipient', 'address'),
                                  ('cap', 'uint'), ('spent', 'uint'), ('expiresAt', 'uint'), ('active', 'bool')])],
    {'name': 'grant2.spent', 'kind': 'uint', 'getter': 'getGrant(uint256)', 'args': ['2'], 'word': 4},
    {'name': 'grant2.active', 'kind': 'bool', 'getter': 'getGrant(uint256)', 'args': ['2'], 'word': 6},
    {'name': 'payee.balance', 'kind': 'uint', 'balance': 'payee'},
]


def build():
    return {
        'format': 'fe-compatibility-scenarios', 'schema_version': 1, 'interface': 'treasury-v0 revision 1',
        'interface_sha256': hashlib.sha256(ABI.read_bytes()).hexdigest(),
        'actors': {'owner': 0, 'delegate': 1, 'recipient': 2, 'outsider': 3},
        'deployment': {'treasury_args': [R('owner')], 'aux_order': ['rejecting', 'reentrant', 'batcher'],
                       'reentrant_args': [R('target'), '1']},
        'state': STATE, 'scenarios': scenarios(),
        'provenance': {'generator': 'scripts/make-corpus.py',
                       'source': 'spec/vendor/treasury-v0/treasury-v0.md revision 1; expectations written from the '
                                 'specification, never from running an implementation'},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    text = json.dumps(build(), indent=2) + '\n'
    if args.check:
        if OUT.read_text() != text:
            sys.exit('fixtures/behavior/treasury-v0.json is not reproduced by scripts/make-corpus.py')
        print('PASS behavioral corpus reproduced byte-for-byte')
        return
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    data = json.loads(text)
    print(f'Wrote {OUT.relative_to(ROOT)}: {len(data["scenarios"])} scenarios, '
          f'{sum(len(s["steps"]) for s in data["scenarios"])} actions')


if __name__ == '__main__':
    main()
