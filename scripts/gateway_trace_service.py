#!/usr/bin/env python3
"""Stage/remove one runtime-only diagnostic drop-in. Never restart a service."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys

# Local operator supplies these; no server identity is embedded in the package.
UNIT = None
STATE = None
PACKAGE = None
EXPECTED = 'e522174564eed7c90b60c8ebff8536f40bc41f7938efb5535d9281ca7e5a70df'
TOOLS_EXPECTED = '5efc8c5eb2079a359adedf3e2f8abfb93780f5bac54b4314bc3cba1e2c9873c5'
NAME = '90-ember-memory-trace-v1.conf'
MARKER = '# Ember bounded memory diagnostic v1; no automatic restart\n'


def quote(value):
    if any(c in value for c in '\r\n\0'):
        raise ValueError('Environment value contains unsupported control characters')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def render(env, hook, executable, argv, flags):
    if env.get('OPENCLAW_STATE_DIR') != STATE or env.get('OPENCLAW_SYSTEMD_UNIT') != UNIT:
        raise ValueError('Live service environment does not identify the requested gateway')
    if 'gateway-trace-preload' in env.get('NODE_OPTIONS', ''):
        raise ValueError('A gateway diagnostic preload is already configured')
    if flags:
        raise ValueError('ExecStart has special execution flags; stop for local review')
    if not isinstance(executable, str) or not Path(executable).is_absolute() or Path(executable).name not in {'node', 'nodejs'}:
        raise ValueError('Expected ExecStart to launch Node directly; stop for local review')
    if not argv or argv[0] != executable or 'gateway' not in argv[1:]:
        raise ValueError('ExecStart is not the expected direct Node gateway command')
    hook = str(hook)
    if any(not isinstance(arg, str) or any(c in arg for c in '\r\n\0$') for arg in [hook, *argv]):
        raise ValueError('ExecStart uses variable expansion or unsupported characters; stop for local review')
    if any('gateway-trace-preload' in arg for arg in argv):
        raise ValueError('A diagnostic preload is already in ExecStart')
    traced_argv = [executable, '--require', hook, *argv[1:]]
    # Override ONLY ExecStart plus diagnostic scope. Environment and
    # EnvironmentFiles, including the next start's NODE_OPTIONS, stay intact.
    return (MARKER + '[Service]\nExecStart=\nExecStart=' + ' '.join(quote(arg) for arg in traced_argv)
            + '\nEnvironment="EMBER_GATEWAY_TRACE=1"\n'
            + ''.join('Environment=' + quote(key + '=' + value) + '\n' for key, value in {
                'EMBER_TRACE_UNIT': UNIT, 'EMBER_TRACE_STATE_DIR': STATE,
                'EMBER_TRACE_PACKAGE_DIR': str(PACKAGE)}.items()))


def read_live_scope(pid):
    if not isinstance(pid, int) or pid <= 0:
        raise RuntimeError('Service MainPID is unavailable')
    raw = Path('/proc') / str(pid) / 'environ'
    if raw.stat().st_uid != os.getuid():
        raise RuntimeError('MainPID belongs to another account')
    allowed = {b'OPENCLAW_STATE_DIR', b'OPENCLAW_SYSTEMD_UNIT', b'NODE_OPTIONS'}
    selected = {}
    for entry in raw.read_bytes().split(b'\0'):
        key, sep, value = entry.partition(b'=')
        if sep and key in allowed:
            selected[key.decode()] = value.decode('utf-8', errors='strict')
    return selected


def bus(*args):
    result = subprocess.run(['busctl', '--user', '--json=short', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Could not read typed systemd launch metadata; nothing restarted')
    try:
        return json.loads(result.stdout)
    except (ValueError, TypeError):
        raise RuntimeError('Unrecognized systemd launch metadata; nothing restarted') from None


def parse_exec_start(value):
    if not isinstance(value, dict) or value.get('type') != 'a(sasasttttuii)':
        raise RuntimeError('Unexpected ExecStartEx signature')
    data = value.get('data')
    # busctl method-message JSON may wrap one array value; property JSON may
    # expose it directly. Accept only one fully typed command in either form.
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], list) and data[0] and isinstance(data[0][0], list):
        data = data[0]
    if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], list) or len(data[0]) != 10:
        raise RuntimeError('Expected exactly one ExecStart command')
    row = data[0]
    if not isinstance(row[0], str) or not isinstance(row[1], list) or not all(isinstance(arg, str) for arg in row[1]) or not isinstance(row[2], list) or not all(isinstance(flag, str) for flag in row[2]):
        raise RuntimeError('Unexpected ExecStartEx command fields')
    if not all(type(number) is int for number in row[3:]):
        raise RuntimeError('Unexpected ExecStartEx accounting fields')
    return row[0], row[1], row[2]


def read_exec_start():
    unit = bus('call', 'org.freedesktop.systemd1', '/org/freedesktop/systemd1',
               'org.freedesktop.systemd1.Manager', 'GetUnit', 's', UNIT)
    if not isinstance(unit, dict) or unit.get('type') != 'o':
        raise RuntimeError('Unexpected service object metadata')
    obj = unit.get('data')
    if isinstance(obj, list) and len(obj) == 1:
        obj = obj[0]
    if not isinstance(obj, str) or not re.fullmatch(r'/org/freedesktop/systemd1/unit/[A-Za-z0-9_]+', obj):
        raise RuntimeError('Unexpected service object path')
    return parse_exec_start(bus('get-property', 'org.freedesktop.systemd1', obj,
                               'org.freedesktop.systemd1.Service', 'ExecStartEx'))


def run(*args):
    result = subprocess.run(['systemctl', '--user', *args], capture_output=True, text=True)
    if result.returncode:
        # systemctl error text can contain service configuration; never relay it.
        raise RuntimeError('systemctl failed; inspect locally, do not paste environment values')
    return result.stdout


def dropin_path():
    runtime = Path('/run/user') / str(os.getuid())
    if not runtime.is_dir() or runtime.stat().st_uid != os.getuid():
        raise RuntimeError('Expected user runtime directory unavailable')
    return runtime / 'systemd/user' / (UNIT + '.d') / NAME


def main():
    global UNIT, STATE, PACKAGE
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true')
    group.add_argument('--stage', action='store_true')
    group.add_argument('--remove', action='store_true')
    parser.add_argument('--unit', required=True)
    parser.add_argument('--state-dir')
    parser.add_argument('--package-dir')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', args.unit):
        raise ValueError('Expected one explicit systemd service name')
    UNIT = args.unit
    if not args.remove:
        if not args.state_dir or not args.package_dir or not Path(args.state_dir).is_absolute() or not Path(args.package_dir).is_absolute():
            raise ValueError('Check/stage require absolute state-dir and package-dir')
        STATE = args.state_dir
        PACKAGE = Path(args.package_dir)
    target = dropin_path()
    digest_path = target.with_suffix('.sha256')
    if args.remove:
        if not target.exists() and not digest_path.exists():
            run('daemon-reload')
            print(json.dumps({'removed': False, 'restart_performed': False}))
            return
        if target.is_symlink() or digest_path.is_symlink():
            raise RuntimeError('Refusing a symlinked diagnostic drop-in')
        data = target.read_bytes()
        if not data.startswith(MARKER.encode()) or hashlib.sha256(data).hexdigest() != digest_path.read_text().strip():
            raise RuntimeError('Drop-in differs from staged bytes; nothing removed')
        target.unlink()
        digest_path.unlink()
        run('daemon-reload')
        print(json.dumps({'removed': True, 'restart_performed': False}))
        return
    if target.exists() or digest_path.exists():
        raise RuntimeError('Diagnostic drop-in already exists; remove it first')
    source = PACKAGE / 'dist/extensions/memory-core/manager-runtime.js'
    if hashlib.sha256(source.read_bytes()).hexdigest() != EXPECTED:
        raise RuntimeError('Installed manager does not match V5')
    if hashlib.sha256((PACKAGE / 'dist/tools-DNmkgIrY.js').read_bytes()).hexdigest() != TOOLS_EXPECTED:
        raise RuntimeError('Installed search tools do not match expected source')
    if json.loads((PACKAGE / 'package.json').read_text()).get('version') != '2026.8.1':
        raise RuntimeError('Unexpected OpenClaw version')
    values = {}
    for line in run('show', UNIT, '-p', 'MainPID', '-p', 'EnvironmentFiles', '-p', 'ActiveState').splitlines():
        key, sep, value = line.partition('=')
        if sep:
            values[key] = value
    if values.get('ActiveState') != 'active':
        raise RuntimeError('Ember is not currently active; do not change service setup')
    try:
        pid = int(values.get('MainPID', '0'))
    except ValueError:
        raise RuntimeError('Service MainPID is unavailable') from None
    env = read_live_scope(pid)
    executable, argv, flags = read_exec_start()
    hook = Path(__file__).resolve().with_name('gateway-trace-preload.cjs')
    for filename in ['gateway-trace-preload.cjs', 'gateway-trace-loader.mjs', 'gateway-trace-runtime.cjs']:
        if not hook.with_name(filename).is_file():
            raise RuntimeError('Diagnostic package is incomplete')
    content = render(env, hook, executable, argv, flags)
    if args.stage:
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode()
        with os.fdopen(os.open(digest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
            f.write(hashlib.sha256(data).hexdigest() + '\n')
        try:
            with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as f:
                f.write(content)
        except Exception:
            digest_path.unlink()
            raise
        try:
            run('daemon-reload')
            loaded = read_exec_start()
            expected_argv = [executable, '--require', str(hook), *argv[1:]]
            if loaded != (executable, expected_argv, flags):
                raise RuntimeError('Staged launch command did not read back exactly')
        except Exception:
            target.unlink()
            digest_path.unlink()
            run('daemon-reload')
            raise RuntimeError('Staged launch verification failed; diagnostic override removed; no restart') from None
    print(json.dumps({'v5_hash': 'matched', 'ember_service_scope': 'matched',
                      'launch_method': 'node-cli-require', 'environment_files_unchanged': True,
                      'node_options_unchanged': True, 'staged': args.stage, 'restart_performed': False,
                      'dropin': str(target) if args.stage else None}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Fixed local exception messages only; no exception details from OS/config.
        if isinstance(exc, (ValueError, RuntimeError)):
            print(str(exc), file=sys.stderr)
        else:
            print('Diagnostic setup failed; inspect locally. No restart was performed.', file=sys.stderr)
        sys.exit(1)
