"""Ephemeral pinned Anvil node and JSON-RPC. Copied from fe-replay host/evm_chain.py, itself adapted
from Fe Capabilities scripts/local_chain.py (MIT, same owner); see NOTICE.md."""
import functools
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request


@functools.lru_cache(maxsize=None)
def cast(*arguments):
    return subprocess.check_output(['cast', *map(str, arguments)], text=True).strip()


class RpcError(RuntimeError):
    def __init__(self, error):
        self.error = error
        super().__init__(str(error))


class LocalChain:
    def __init__(self, root):
        self.root = Path(root)
        self.receipts = []
        self.errors = []
        self.versions = {}
        self.node = None
        self.log = None

    def __enter__(self):
        manifest = json.loads((self.root / 'toolchain.json').read_text())
        for tool in ['anvil', 'cast']:
            version = subprocess.check_output([tool, '--version'], text=True).strip()
            if manifest['foundry']['commit'] not in version:
                raise RuntimeError(f'{tool} differs from the pinned Foundry commit')
            self.versions[tool] = version
        with socket.socket() as reservation:
            reservation.bind(('127.0.0.1', 0))
            port = reservation.getsockname()[1]
        self.url = f'http://127.0.0.1:{port}'
        self.log = tempfile.TemporaryFile()
        try:
            self.node = subprocess.Popen(['anvil', '--hardfork', 'osaka', '--host', '127.0.0.1',
                                          '--port', str(port), '--timestamp', '1700000000', '--chain-id', '31337', '--base-fee', '0', '--silent'],
                                         stdout=self.log, stderr=self.log)
            deadline = time.monotonic() + 15
            while True:
                if self.node.poll() is not None:
                    self.log.seek(0)
                    raise RuntimeError('Anvil exited: ' + self.log.read().decode())
                try:
                    self.accounts = self.rpc('eth_accounts', [])
                    return self
                except (urllib.error.URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Anvil startup timed out')
                    time.sleep(0.1)
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *exception):
        if self.node is not None:
            self.node.terminate()
            try:
                self.node.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.node.kill()
                self.node.wait()
        if self.log is not None:
            self.log.close()

    def rpc(self, method, params):
        payload = json.dumps({'jsonrpc': '2.0', 'id': 1, 'method': method, 'params': params}).encode()
        request = urllib.request.Request(self.url, payload, {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=3) as response:
            result = json.load(response)
        if 'error' in result:
            raise RpcError(result['error'])
        return result['result']

    def call(self, tx):
        return self.rpc('eth_call', [tx, 'latest'])

    def expect_error(self, label, tx, expected=None):
        try:
            self.call(tx)
        except RpcError as failure:
            if expected is not None:
                assert failure.error.get('data') == expected, (label, failure.error, expected)
            self.errors.append({'label': label, 'transaction': tx, 'error': failure.error})
        else:
            raise AssertionError(f'{label}: expected rejection')

    def send(self, label, to=None, data='0x', value=0, sender=None, success=True):
        tx = {'from': sender or self.accounts[0], 'data': data, 'value': hex(value), 'gas': hex(2_000_000), 'gasPrice': '0x1'}
        if to is not None:
            tx['to'] = to
        tx_hash = self.rpc('eth_sendTransaction', [tx])
        deadline = time.monotonic() + 10
        while True:
            receipt = self.rpc('eth_getTransactionReceipt', [tx_hash])
            if receipt:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(f'{label}: receipt timeout')
            time.sleep(0.1)
        if success is not None:
            assert int(receipt['status'], 16) == int(success), (label, receipt)
        if success is False:
            assert receipt['logs'] == [], (label, receipt)
        self.receipts.append({'label': label, 'transaction': tx, 'receipt': receipt})
        return receipt
