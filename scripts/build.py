#!/usr/bin/env python3
"""Build the Phase 0 pair, the seeded Fe variant and the native Fe checker.

Outputs go to ignored .tools/build/ and host/checker-native/out/; every artifact
digest and the source manifest are recorded in .tools/build/build.json.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'host'))
from common import (ROOT, BUILD, STAMP, CHECKER, VARIANTS, TREASURY_VARIANTS, InfrastructureError, sha, hex_sha,
                    fe_compiler, solc_compiler, source_manifest)


def main():
    fe, fe_info = fe_compiler()
    solc, solc_info = solc_compiler()
    STAMP.unlink(missing_ok=True)
    if BUILD.exists():
        shutil.rmtree(BUILD)
    commands = []

    def run(command):
        result = subprocess.run([str(c) for c in command], cwd=ROOT, capture_output=True, text=True, timeout=300)
        commands.append({'command': [str(c).replace(str(ROOT), '<root>') for c in command], 'exit': result.returncode})
        if result.returncode:
            raise InfrastructureError(f'{command}\n{result.stdout}\n{result.stderr}')
        print('PASS ' + ' '.join(Path(str(c)).name if i == 0 else str(c).replace(str(ROOT) + '/', '')
                                 for i, c in enumerate(command)), flush=True)

    solidity = BUILD / 'solidity'
    run([solc, '--evm-version', 'osaka', '--optimize', '--optimize-runs', '200', '--bin', '--bin-runtime', '--abi',
         '-o', solidity, 'contracts/solidity/Meter.sol', 'contracts/solidity/Codec.sol',
         'contracts/solidity/Treasury.sol', 'contracts/solidity/Harness.sol'])
    vendored = ROOT / 'contracts/fe/treasury'
    provenance = json.loads((vendored / 'provenance.json').read_text())
    for path, digest in provenance['files'].items():
        if sha(vendored / path) != digest:
            raise InfrastructureError(f'Vendored Fe treasury file changed: {path}')
    treasury_builds = [('fe-treasury', vendored / 'treasury')]
    for variant, edits in TREASURY_VARIANTS.items():
        source = BUILD / 'sources' / f'treasury-{variant[3:]}'
        shutil.copytree(vendored, source, ignore=shutil.ignore_patterns('out', 'upstream'))
        for path, old, new in edits:
            text = (source / path).read_text()
            if text.count(old) != 1:
                raise InfrastructureError(f'{variant}: seeded mutation no longer applies exactly once')
            (source / path).write_text(text.replace(old, new))
        treasury_builds.append((variant, source / 'treasury'))
    for variant, path in treasury_builds:
        run([fe, 'build', path, '--backend', 'sonatina', '--profile', 'release', '-O', '1',
             '--emit', 'bytecode,runtime-bytecode,abi,metadata', '--out-dir', BUILD / variant])
    builds = [('fe', ROOT / 'contracts/fe/meter'), ('fe-codec', ROOT / 'contracts/fe/codec')]
    mutated = {}
    for variant, edits in VARIANTS.items():
        source = BUILD / 'sources' / ('meter-faulty' if variant == 'fe-faulty' else f'meter-{variant[3:]}')
        shutil.copytree(ROOT / 'contracts/fe/meter', source, ignore=shutil.ignore_patterns('out'))
        source_file = source / 'src/lib.fe'
        text = source_file.read_text()
        for old, new in edits:
            if text.count(old) != 1:
                raise InfrastructureError(f'{variant}: seeded mutation no longer applies exactly once')
            text = text.replace(old, new)
        source_file.write_text(text)
        mutated[variant] = sha(source_file)
        builds.append((variant, source))
    for variant, path in builds:
        run([fe, 'build', path, '--backend', 'sonatina', '--profile', 'release', '-O', '1',
             '--emit', 'bytecode,runtime-bytecode,abi,metadata', '--out-dir', BUILD / variant])
    run([fe, 'build', 'host/checker-native', '--backend', 'native', '--emit', 'executable', '-O', '1'])

    targets = {
        'solidity': {'creation': 'solidity/Meter.bin', 'runtime': 'solidity/Meter.bin-runtime', 'abi': 'solidity/Meter.abi',
                     'compiler': solc_info['version'], 'settings': 'solc --evm-version osaka --optimize --optimize-runs 200'},
        'fe': {'creation': 'fe/Meter.bin', 'runtime': 'fe/Meter.runtime.bin', 'abi': 'fe/Meter.abi.json',
               'compiler': fe_info['version'], 'settings': 'fe build --backend sonatina --profile release -O 1'},
        **{variant: {'creation': f'{variant}/Meter.bin', 'runtime': f'{variant}/Meter.runtime.bin',
                     'abi': f'{variant}/Meter.abi.json', 'compiler': fe_info['version'],
                     'settings': 'fe build --backend sonatina --profile release -O 1',
                     'fault': 'intentional: ' + ' / '.join(new.split('INTENTIONAL ')[1].split('\n')[0]
                                                         for _, new in edits),
                     'mutated_source_sha256': mutated[variant]} for variant, edits in VARIANTS.items()},
    }
    targets['solidity-codec'] = {'creation': 'solidity/Codec.bin', 'runtime': 'solidity/Codec.bin-runtime',
                                 'abi': 'solidity/Codec.abi', 'compiler': solc_info['version'],
                                 'settings': targets['solidity']['settings']}
    targets['fe-codec'] = {'creation': 'fe-codec/Codec.bin', 'runtime': 'fe-codec/Codec.runtime.bin',
                           'abi': 'fe-codec/Codec.abi.json', 'compiler': fe_info['version'],
                           'settings': targets['fe']['settings']}
    targets['solidity-treasury'] = {'creation': 'solidity/Treasury.bin', 'runtime': 'solidity/Treasury.bin-runtime',
                                    'abi': 'solidity/Treasury.abi', 'compiler': solc_info['version'],
                                    'settings': targets['solidity']['settings']}
    for variant in ('fe-treasury', *TREASURY_VARIANTS):
        targets[variant] = {'creation': f'{variant}/Treasury.bin', 'runtime': f'{variant}/Treasury.runtime.bin',
                            'abi': f'{variant}/Treasury.abi.json', 'compiler': fe_info['version'],
                            'settings': targets['fe']['settings'],
                            'source': 'contracts/fe/treasury (vendored from Fe Capabilities ba6893c)'}
        if variant in TREASURY_VARIANTS:
            targets[variant]['fault'] = 'intentional: ' + ' / '.join(
                new.split('INTENTIONAL ')[1].split('\n')[0] for _, _, new in TREASURY_VARIANTS[variant])
    for name in ('RejectingRecipient', 'ReentrantRecipient', 'Batcher'):
        targets[f'harness-{name}'] = {'creation': f'solidity/{name}.bin', 'runtime': f'solidity/{name}.bin-runtime',
                                      'abi': f'solidity/{name}.abi', 'compiler': solc_info['version'],
                                      'settings': targets['solidity']['settings'], 'role': 'shared test fixture'}
    for target in targets.values():
        target['creation_sha256'] = hex_sha(BUILD / target['creation'])
        target['runtime_sha256'] = hex_sha(BUILD / target['runtime'])
    artifacts = {str(p.relative_to(ROOT)): sha(p) for p in sorted(BUILD.rglob('*'))
                 if p.is_file() and 'sources' not in p.relative_to(BUILD).parts}
    artifacts[str(CHECKER.relative_to(ROOT))] = sha(CHECKER)
    stamp = {'format': 'fe-compatibility-build-v1', 'fe': fe_info, 'solc': solc_info, 'targets': targets,
             'sources': source_manifest(), 'artifacts': artifacts, 'mutations': {k: [list(e) for e in v] for k, v in VARIANTS.items()}, 'commands': commands}
    STAMP.write_text(json.dumps(stamp, indent=2) + '\n')
    print(f'PASS build stamp {STAMP.relative_to(ROOT)}', flush=True)


if __name__ == '__main__':
    try:
        main()
    except InfrastructureError as error:
        sys.exit(f'Build failed: {error}')
