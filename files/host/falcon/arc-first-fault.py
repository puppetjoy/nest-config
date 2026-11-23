#!/usr/bin/env python3
"""Retain Arc PM/AER prehistory at the first uncorrected error; never reset it.

Temporary diagnostic for Falcon endpoint loss. No PCI/register/power writes,
GPU workload, polling daemon or automatic recovery. Remove after investigation.
"""
import hashlib
import json
import pathlib
import sys

TRACEFS = pathlib.Path('/sys/kernel/tracing')
INSTANCE = TRACEFS / 'instances/falcon-arc-first-fault'
STATE = pathlib.Path('/run/falcon-arc-first-fault')
DEVICES = ('0000:00:02.0', '0000:03:00.0', '0000:04:01.0',
           '0000:04:04.0', '0000:05:00.0', '0000:06:00.0')


def device_filter(field):
    return '(' + ' || '.join(f'{field} == "{name}"' for name in DEVICES) + ')'


FILTERS = {
    'ras/aer_event': device_filter('dev_name'),
    'rpm/rpm_suspend': device_filter('name'),
    'rpm/rpm_resume': device_filter('name'),
    'rpm/rpm_idle': device_filter('name'),
    'power/device_pm_callback_start': device_filter('device'),
    'power/device_pm_callback_end': device_filter('device'),
}
TRIGGER = 'traceoff:1 if ' + device_filter('dev_name') + ' && severity != 2'
SPEC = hashlib.sha256(json.dumps([FILTERS, TRIGGER, 256], sort_keys=True).encode()).hexdigest()


def put(relative, value):
    (INSTANCE / relative).write_text(value + '\n')


def status():
    trigger = (INSTANCE / 'events/ras/aer_event/trigger').read_text().strip()
    assert trigger.startswith(('traceoff:count=1 if ', 'traceoff:count=0 if ')), trigger
    return {'instance': str(INSTANCE), 'boot_id': pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'tracing_on': (INSTANCE / 'tracing_on').read_text().strip(),
            'trigger': trigger, 'buffer_total_size_kb': (INSTANCE / 'buffer_total_size_kb').read_text().strip(),
            'armed': 'traceoff:count=1 if ' in trigger,
            'frozen': 'traceoff:count=0 if ' in trigger}


def main():
    assert sys.argv[1:] in ([], ['--status']), 'Only setup and --status are supported; never rearm implicitly'
    boot = pathlib.Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    expected = {'boot_id': boot, 'spec_sha256': SPEC}
    marker = STATE / 'armed.json'
    if INSTANCE.exists():
        # Preserve even a frozen capture on service restart or Puppet convergence.
        assert marker.is_file() and json.loads(marker.read_text()) == expected, 'Existing trace requires evidence reconciliation; refusing to clear it'
        print(json.dumps(status(), indent=2))
        return
    assert not sys.argv[1:], 'No capture instance exists'
    assert not marker.exists(), 'Retained marker without instance; refusing implicit rearm'
    assert pathlib.Path('/sys/bus/pci/devices/0000:05:00.0/device').read_text().strip() == '0x56a1'
    # Validate tracepoint availability before allocating or changing tracing state.
    for event in FILTERS:
        assert (TRACEFS / 'events' / event / 'format').is_file(), event
    available = (TRACEFS / 'events/ras/aer_event/trigger').read_text()
    assert 'traceoff' in available, 'Kernel lacks the required event trigger'
    STATE.mkdir(mode=0o700, exist_ok=True)
    INSTANCE.mkdir()
    put('tracing_on', '0')
    put('buffer_size_kb', '256')
    put('trace_clock', 'mono')
    put('options/overwrite', '1')
    for event, expression in FILTERS.items():
        put(f'events/{event}/filter', expression)
    put('events/ras/aer_event/trigger', TRIGGER)
    for event in FILTERS:
        put(f'events/{event}/enable', '1')
    # Publish preservation identity before admission. A partial setup fails closed,
    # and does not delete a potentially valuable trace on a subsequent invocation.
    with marker.open('x') as stream:
        json.dump(expected, stream)
    marker.chmod(0o600)
    put('tracing_on', '1')
    print(json.dumps(status(), indent=2))


if __name__ == '__main__':
    main()
