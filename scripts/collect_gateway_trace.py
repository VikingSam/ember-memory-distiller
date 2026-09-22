#!/usr/bin/env python3
"""Read one Ember journal invocation; emit diagnostic records only."""
import argparse
import json
import re
import subprocess
import sys

PREFIX = 'EMBER_GATEWAY_TRACE '
EVENTS = {'capture_start','module_loaded','start','end','health','record_cap','capture_end','cpu_samples','profiler_unavailable'}
PHASES = {'manager_get','search','provider_init','sync_admitted','background_maintenance','sync_pass','startup_catchup','session_update','memory_files','session_files','batch_embedding','query_embedding','provider_probe','bootstrap_probe','embedding_request','retry_sleep','fts','vector','generation_read_wait','generation_write_wait','generation_write_hold','workspace_operation','workspace_hold'}
NUMBERS = {'pid','at_ms','id','parent','elapsed_ms','items','timeout_ms','duration_ms','max_records','limit','cpu_ms','event_loop_max_ms','sample_interval_us','line','samples'}
REASONS = {'watch','interval','session-delta','session-startup-catchup','cli','search','session-start','retry','fallback','other'}
ERRORS = {'SQLITE_BUSY','SQLITE_LOCKED','ETIMEDOUT','ECONNRESET','ECONNREFUSED','EAI_AGAIN','ABORT_ERR','sqlite_locked','rate_limit','timeout','aborted','transport','other'}


def project(record):
    """Never forward arbitrary string fields, even from a diagnostic-looking line."""
    out = {}
    for key, value in record.items():
        if key in NUMBERS and (type(value) is int or key == 'parent' and value is None):
            out[key] = value
        elif key in {'ok','record_cap_reached'} and type(value) is bool:
            out[key] = value
        elif key == 'event' and isinstance(value, str) and value in EVENTS:
            out[key] = value
        elif key == 'phase' and isinstance(value, str) and value in PHASES:
            out[key] = value
        elif key == 'reason' and isinstance(value, str) and value in REASONS:
            out[key] = value
        elif key == 'error_class' and isinstance(value, str) and (value in ERRORS or re.fullmatch(r'http_[45][0-9]{2}', value)):
            out[key] = value
        elif key == 'attribution' and isinstance(value, str) and value in {'leaf','openclaw_caller','unattributed'}:
            out[key] = value
        elif key == 'mode' and value == 'observe-v5':
            out[key] = value
        elif key == 'note' and value == 'each_sample_attributed_once_not_lock_wait_time':
            out[key] = value
        elif key == 'file' and isinstance(value, str) and (value in {'outside-openclaw','(idle)','(garbage collector)','(program)'} or re.fullmatch(r'[A-Za-z0-9_.-]+\.[cm]?js', value)):
            out[key] = value
        elif key == 'active_ids' and isinstance(value, list):
            out[key] = [v for v in value[:256] if type(v) is int]
        elif key in {'active','frames'} and isinstance(value, list):
            out[key] = [project(v) for v in value[:256] if isinstance(v, dict)]
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--invocation', required=True)
    parser.add_argument('--unit', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+\.service', args.unit):
        parser.error('Expected one explicit systemd service name')
    if not re.fullmatch(r'[0-9a-f]{32}', args.invocation):
        parser.error('Expected one 32-character invocation ID')
    proc = subprocess.Popen([
        'journalctl', '--user', '-u', args.unit,
        '_SYSTEMD_INVOCATION_ID=' + args.invocation, '-o', 'cat', '--no-pager'
    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    count = 0
    total = 0
    records = []
    for line in proc.stdout:
        total += len(line)
        if total > 20_000_000:
            proc.kill()
            proc.wait()
            raise RuntimeError('Journal exceeded local reading limit; nothing exported')
        if not line.startswith(PREFIX):
            continue
        try:
            record = json.loads(line[len(PREFIX):])
        except (ValueError, TypeError):
            continue
        if not isinstance(record, dict) or not isinstance(record.get('pid'), int) or not isinstance(record.get('at_ms'), int):
            continue
        if not isinstance(record.get('event'),str) or record.get('event') not in EVENTS:
            continue
        records.append(project(record))
        count += 1
        if count > 10000:
            proc.kill()
            proc.wait()
            raise RuntimeError('Too many diagnostic records; nothing exported')
    if proc.wait():
        raise RuntimeError('Journal unavailable; nothing exported')
    if not records:
        raise RuntimeError('No diagnostic records in that invocation')
    for record in records:
        print(PREFIX + json.dumps(record, separators=(',', ':')))


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
