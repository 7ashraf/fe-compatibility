"""One isolated pinned Anvil (Osaka) world: roles, deployment and calls, with raw observations.

Returndata comes from debug_traceTransaction and is cross-checked against an
independent eth_call at the parent block. Disagreement is an infrastructure error.
"""
import hashlib

from common import InfrastructureError, ROOT
from evm_chain import LocalChain, RpcError, cast

GENESIS = 1700000000
LIMIT = 256


def raw_hex(value):
    text = (value or '').removeprefix('0x').lower()
    if len(text) % 2:
        raise InfrastructureError('Odd-length hex from RPC')
    bytes.fromhex(text)
    return '0x' + text


class World:
    def __init__(self, deployer=0, caller=1, accounts=None):
        """accounts: extra role -> Anvil account index (for example owner, delegate, outsider)."""
        self.indices = {'deployer': deployer, 'caller': caller, **(accounts or {})}
        self.chain = None
        self.clock = GENESIS
        self.gas_paid = {}

    def __enter__(self):
        self.chain = LocalChain(ROOT).__enter__()
        accounts = [a.lower() for a in self.chain.accounts]
        self.roles = {role: accounts[index] for role, index in self.indices.items()}
        self.roles['zero'] = '0x' + '00' * 20
        return self

    def __exit__(self, *exception):
        self.chain.__exit__(*exception)

    @property
    def versions(self):
        return self.chain.versions

    def advance(self, seconds):
        """Move the schedule forward; the next transaction is mined at clock + 1."""
        self.clock += seconds

    def _transact(self, label, data, to=None, sender=None, value=0):
        self.clock += 1
        self.chain.rpc('evm_setNextBlockTimestamp', [self.clock])
        self.chain.send(label, to=to, data=data, sender=sender, success=None, value=value)
        receipt = self.chain.receipts[-1]['receipt']
        block = self.chain.rpc('eth_getBlockByNumber', [receipt['blockNumber'], False])
        if int(block['timestamp'], 16) != self.clock:
            raise InfrastructureError('Mined timestamp differs from the scheduled one')
        success = int(receipt['status'], 16) == 1
        trace = self.chain.rpc('debug_traceTransaction', [receipt['transactionHash'],
                               {'disableStorage': True, 'disableMemory': True, 'disableStack': True}])
        if bool(trace.get('failed')) == success:
            raise InfrastructureError(f'{label}: receipt status and trace disagree')
        returndata = raw_hex(trace.get('returnValue', ''))
        call = {'from': sender or self.roles['deployer'], 'data': data, 'gas': hex(2_000_000), 'value': hex(value)}
        if to is not None:
            call['to'] = to
        parent = hex(int(receipt['blockNumber'], 16) - 1)
        # Replay on the parent state with the mined block's timestamp and number, so time-dependent
        # outcomes (for example Expired(expiresAt, now)) are reproduced exactly.
        overrides = {'time': hex(self.clock), 'number': receipt['blockNumber']}
        fee = int(receipt['gasUsed'], 16) * int(receipt['effectiveGasPrice'], 16)
        payer = (sender or self.roles['deployer']).lower()
        self.gas_paid[payer] = self.gas_paid.get(payer, 0) + fee
        try:
            via_call, call_success = raw_hex(self.chain.rpc('eth_call', [call, parent, {}, overrides])), True
        except RpcError as error:
            via_call, call_success = raw_hex((error.error or {}).get('data', '')), False
        if call_success != success or (via_call != returndata and not (to is None and success)):
            raise InfrastructureError(f'{label}: trace and eth_call disagree')
        logs = [{'address': log['address'].lower(), 'topics': [t.lower() for t in log['topics']],
                 'data': raw_hex(log['data'])} for log in receipt['logs']]
        if not success and logs:
            raise InfrastructureError(f'{label}: reverted transaction has logs')
        return receipt, {'success': success, 'returndata': returndata, 'returndata_via_eth_call': via_call,
                         'logs': logs, 'gas_used': int(receipt['gasUsed'], 16),
                         'block': int(receipt['blockNumber'], 16), 'timestamp': self.clock}

    def deploy(self, creation_hex, constructor_args_hex='', name='target'):
        """Deploy from the deployer role as role `name`. A failed deployment is returned, not raised."""
        receipt, observation = self._transact('deploy', creation_hex + constructor_args_hex.removeprefix('0x'),
                                              sender=self.roles['deployer'])
        address = (receipt.get('contractAddress') or '').lower() if observation['success'] else None
        if observation['success']:
            code = self.chain.rpc('eth_getCode', [address, 'latest'])
            if code != observation['returndata_via_eth_call'] or len(code) <= 2:
                raise InfrastructureError('Deployment: eth_call runtime differs from deployed code')
            observation['runtime_code_sha256'] = hashlib.sha256(bytes.fromhex(code[2:])).hexdigest()
            self.roles[name] = address
        # The runtime code isn't behavior; only a failed deployment's revert bytes reach the checker.
        observation['checker_returndata'] = '0x' if observation['success'] else observation['returndata']
        observation['address'] = address
        return observation

    def call(self, calldata, sender_role='caller', state=(), to_role='target', value=0):
        """Run one call, then read the declared public state at the new block.

        state entries are (name, signature, kind) for a one-word getter on the target, or dicts
        {'name', 'kind', 'getter', 'args', 'word'} for one word of a multi-word getter, or
        {'name', 'kind', 'balance': role} for an account balance.
        """
        if 'target' not in self.roles:
            raise InfrastructureError('Call before a successful deployment')
        _, observation = self._transact('call', calldata, to=self.roles[to_role], sender=self.roles[sender_role],
                                        value=value)
        if len(observation['returndata']) > 2 + 2 * LIMIT:
            raise InfrastructureError('Returndata exceeds the 256-byte observation limit')
        cache = {}
        observation['state'] = [self.read_state(entry, cache) for entry in state]
        return observation

    def read_state(self, entry, cache):
        if isinstance(entry, tuple):
            name, signature, kind = entry
            entry = {'name': name, 'kind': kind, 'getter': signature, 'args': [], 'word': 0}
        name, kind = entry['name'], entry['kind']
        if 'balance' in entry:
            # ETH movement net of the account's own transaction fees: gas differs by compiler and is
            # accounted separately, never as behavior.
            address = self.roles[entry['balance']]
            value = int(self.chain.rpc('eth_getBalance', [address, 'latest']), 16) + self.gas_paid.get(address, 0)
            return {'name': name, 'kind': kind, 'value': str(value)}
        key = (entry['getter'], tuple(entry['args']))
        if key not in cache:
            data = cast('calldata', entry['getter'], *entry['args'])
            try:
                cache[key] = bytes.fromhex(raw_hex(self.chain.rpc(
                    'eth_call', [{'to': self.roles['target'], 'data': data}, 'latest']))[2:])
            except RpcError as error:
                raise InfrastructureError(f'State getter {entry["getter"]} reverted') from error
        raw = cache[key][32 * entry['word']:32 * entry['word'] + 32]
        if len(raw) != 32:
            raise InfrastructureError(f'State getter {entry["getter"]} has no word {entry["word"]}')
        value = int.from_bytes(raw, 'big', signed=(kind == 'int'))
        text = '0x' + raw.hex()[24:] if kind == 'address' else str(value)
        return {'name': name, 'kind': kind, 'value': text}
