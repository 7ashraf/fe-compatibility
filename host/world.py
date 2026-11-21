"""One isolated pinned Anvil (Osaka) world: roles, deployment and calls, with raw observations.

Returndata comes from debug_traceTransaction and is cross-checked against an
independent eth_call at the parent block. Disagreement is an infrastructure error.
"""
import hashlib

from common import InfrastructureError, ROOT
from evm_chain import LocalChain, RpcError

GENESIS = 1700000000
LIMIT = 256


def raw_hex(value):
    text = (value or '').removeprefix('0x').lower()
    if len(text) % 2:
        raise InfrastructureError('Odd-length hex from RPC')
    bytes.fromhex(text)
    return '0x' + text


class World:
    def __init__(self, deployer=0, caller=1):
        self.indices = {'deployer': deployer, 'caller': caller}
        self.chain = None
        self.clock = GENESIS

    def __enter__(self):
        self.chain = LocalChain(ROOT).__enter__()
        accounts = [a.lower() for a in self.chain.accounts]
        self.roles = {'deployer': accounts[self.indices['deployer']], 'caller': accounts[self.indices['caller']],
                      'zero': '0x' + '00' * 20}
        return self

    def __exit__(self, *exception):
        self.chain.__exit__(*exception)

    @property
    def versions(self):
        return self.chain.versions

    def _transact(self, label, data, to=None, sender=None):
        self.clock += 1
        self.chain.rpc('evm_setNextBlockTimestamp', [self.clock])
        self.chain.send(label, to=to, data=data, sender=sender, success=None)
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
        call = {'from': sender or self.roles['deployer'], 'data': data, 'gas': hex(2_000_000)}
        if to is not None:
            call['to'] = to
        parent = hex(int(receipt['blockNumber'], 16) - 1)
        try:
            via_call, call_success = raw_hex(self.chain.rpc('eth_call', [call, parent])), True
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

    def deploy(self, creation_hex, constructor_args_hex=''):
        """Deploy from the deployer role. A failed deployment is returned, not raised."""
        receipt, observation = self._transact('deploy', creation_hex + constructor_args_hex.removeprefix('0x'),
                                              sender=self.roles['deployer'])
        address = (receipt.get('contractAddress') or '').lower() if observation['success'] else None
        if observation['success']:
            code = self.chain.rpc('eth_getCode', [address, 'latest'])
            if code != observation['returndata_via_eth_call'] or len(code) <= 2:
                raise InfrastructureError('Deployment: eth_call runtime differs from deployed code')
            observation['runtime_code_sha256'] = hashlib.sha256(bytes.fromhex(code[2:])).hexdigest()
            self.roles['target'] = address
        # The runtime code isn't behavior; only a failed deployment's revert bytes reach the checker.
        observation['checker_returndata'] = '0x' if observation['success'] else observation['returndata']
        observation['address'] = address
        return observation

    def call(self, calldata, sender_role='caller'):
        if 'target' not in self.roles:
            raise InfrastructureError('Call before a successful deployment')
        _, observation = self._transact('call', calldata, to=self.roles['target'], sender=self.roles[sender_role])
        if len(observation['returndata']) > 2 + 2 * LIMIT:
            raise InfrastructureError('Returndata exceeds the 256-byte observation limit')
        return observation
