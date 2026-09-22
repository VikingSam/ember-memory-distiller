#!/usr/bin/env python3
"""Stage/remove one runtime-only diagnostic drop-in. Never restart a service."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shlex
import subprocess
import sys

# Local operator supplies these; no server identity is embedded in the package.
UNIT = None
STATE = None
PACKAGE = None
EXPECTED = 'e522174564eed7c90b60c8ebff8536f40bc41f7938efb5535d9281ca7e5a70df'
NAME = '90-ember-memory-trace-v1.conf'
MARKER = '# Ember bounded memory diagnostic v1; no automatic restart\n'


def quote(value):
    if any(c in value for c in '\r\n\0'):
        raise ValueError('Environment value contains unsupported control characters')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%') + '"'


def render(env, hook):
    if env.get('OPENCLAW_STATE_DIR') != STATE or env.get('OPENCLAW_SYSTEMD_UNIT') != UNIT:
        raise ValueError('Effective service Environment does not explicitly identify Ember; stop for review')
    options = env.get('NODE_OPTIONS', '')
    if 'gateway-trace-preload' in options:
        raise ValueError('A gateway diagnostic preload is already configured')
    # Node parses quoted NODE_OPTIONS paths. No shell is used.
    hook = str(hook)
    if any(c in hook for c in '\r\n\0"\\'):
        raise ValueError('Unsupported diagnostic path')
    options = (options + ' --require="' + hook + '"').strip()
    return (MARKER + '[Service]\nEnvironment=' + quote('NODE_OPTIONS=' + options) + '\nEnvironment="EMBER_GATEWAY_TRACE=1"\n'
            + ''.join('Environment=' + quote(key + '=' + value) + '\n' for key, value in {
                'EMBER_TRACE_UNIT': UNIT, 'EMBER_TRACE_STATE_DIR': STATE,
                'EMBER_TRACE_PACKAGE_DIR': str(PACKAGE)}.items()))


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
    if json.loads((PACKAGE / 'package.json').read_text()).get('version') != '2026.8.1':
        raise RuntimeError('Unexpected OpenClaw version')
    values = {}
    for line in run('show', UNIT, '-p', 'Environment', '-p', 'EnvironmentFiles', '-p', 'ActiveState').splitlines():
        key, sep, value = line.partition('=')
        if sep:
            values[key] = value
    if values.get('EnvironmentFiles'):
        raise RuntimeError('Service uses EnvironmentFiles; stop for local review to preserve NODE_OPTIONS')
    if values.get('ActiveState') != 'active':
        raise RuntimeError('Ember is not currently active; do not change service setup')
    env = dict(item.split('=', 1) for item in shlex.split(values.get('Environment', '')) if '=' in item)
    hook = Path(__file__).resolve().with_name('gateway-trace-preload.cjs')
    for filename in ['gateway-trace-preload.cjs', 'gateway-trace-loader.mjs', 'gateway-trace-runtime.cjs']:
        if not hook.with_name(filename).is_file():
            raise RuntimeError('Diagnostic package is incomplete')
    content = render(env, hook)
    if args.stage:
        target.parent.mkdir(parents=True, exist_ok=True)
        data = content.encode()
        with digest_path.open('x') as f:
            f.write(hashlib.sha256(data).hexdigest() + '\n')
        try:
            with target.open('x') as f:
                f.write(content)
        except Exception:
            digest_path.unlink()
            raise
        run('daemon-reload')
    print(json.dumps({'v5_hash': 'matched', 'ember_service_scope': 'matched',
                      'staged': args.stage, 'restart_performed': False,
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
