"""Evaluation-only clock protection; importing this module has no host effects."""
import ctypes
import json
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class ClockInvalid(RuntimeError):
    pass


def ns(value):
    delta = datetime.fromisoformat(value).astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000_000 + delta.microseconds * 1000


class Continuity:
    """Same intersection as evidence.ClockMap, checked at every calibration.

    Never reset an offset, widen intervals, exclude samples or create segments.
    Identity/sequence/footer checks are additional capture-integrity checks.
    """
    def __init__(self):
        self.identity = self.seq = self.last = self.lo = self.hi = None
        self.calibrations = 0
        self.ended = False
        self.error = None

    def fail(self, reason):
        self.error = self.error or reason
        raise ClockInvalid(self.error)

    def feed(self, row):
        if self.error:
            raise ClockInvalid(self.error)
        identity = tuple(row[k] for k in ('run_id', 'worker', 'os_pid', 'session_id'))
        if self.identity is None:
            if row['event'] != 'capture_start' or row['seq'] != 1:
                self.fail('CAPTURE_START_MISSING')
            self.identity = identity
        elif identity != self.identity:
            self.fail('PARTICIPANT_IDENTITY_CHANGED')
        if self.ended or (self.seq is not None and row['seq'] != self.seq + 1):
            self.fail('CAPTURE_SEQUENCE_BROKEN')
        if self.last is not None and row['monotonic_ns'] < self.last:
            self.fail('MONOTONIC_REVERSED')
        self.seq, self.last = row['seq'], row['monotonic_ns']
        if row['event'] == 'db_clock':
            if row['start_ns'] > row['end_ns'] or row['end_ns'] > row['monotonic_ns']:
                self.fail('INVALID_CALIBRATION_BRACKET')
            low, high = ns(row['db_timestamp']) - row['end_ns'], ns(row['db_timestamp']) - row['start_ns']
            self.lo = low if self.lo is None else max(self.lo, low)
            self.hi = high if self.hi is None else min(self.hi, high)
            self.calibrations += 1
            if self.lo > self.hi:
                self.fail('INVALID_CLOCK_RELATION')
        if row['event'] == 'capture_end':
            if row.get('failed_writes', 0):
                self.fail('CAPTURE_WRITES_FAILED')
            self.ended = True

    def finish(self):
        if self.error:
            raise ClockInvalid(self.error)
        if not self.ended or not self.calibrations:
            self.fail('CLOCK_CAPTURE_INCOMPLETE')
        return dict(identity=self.identity, calibrations=self.calibrations, offset_ns=[self.lo, self.hi],
                    last_seq=self.seq, mathematical_relation_valid=True, physical_accreditation=False)


@contextmanager
def prevent_idle_sleep(set_state=None):
    """Scoped ES_SYSTEM_REQUIRED; no power-plan, NTP or clock configuration.

    Windows does not promise protection against explicit sleep or lid closure.
    Must execute and restore on the same conductor thread.
    """
    if set_state is None:
        if os.name != 'nt':
            raise ClockInvalid('WINDOWS_IDLE_GUARD_UNAVAILABLE')
        set_state = ctypes.WinDLL('kernel32', use_last_error=True).SetThreadExecutionState
        set_state.argtypes, set_state.restype = [ctypes.c_uint], ctypes.c_uint
    previous = set_state(0x80000001)
    if not previous:
        raise ClockInvalid('IDLE_GUARD_NOT_ACQUIRED')
    try:
        yield dict(previous_state=previous, requested_state=0x80000001)
    finally:
        if not set_state(previous | 0x80000000):
            raise ClockInvalid('IDLE_GUARD_NOT_RESTORED')


class JournalMonitor:
    """Tail raw participant files; latches stop on invalid evidence.

    No DB queries, runtime hooks, extra polls or time adjustment. A conductor
    must call check() from its existing health checks and close after workers.
    """
    def __init__(self, directory, roles=('ingress', 'planner_1', 'planner_2', 'sender')):
        self.directory = Path(directory)
        self.roles = roles
        self.states = {role: Continuity() for role in roles}
        self.positions = {role: 0 for role in roles}
        self.pending = {role: b'' for role in roles}
        self.done = threading.Event()
        self.error = None
        self.thread = None

    def poll(self):
        for role in self.roles:
            path = self.directory / (role + '.jsonl')
            if not path.exists():
                continue
            if path.stat().st_size < self.positions[role]:
                raise ClockInvalid('JOURNAL_TRUNCATED:' + role)
            with path.open('rb') as stream:
                stream.seek(self.positions[role])
                data = stream.read()
                self.positions[role] = stream.tell()
            parts = (self.pending[role] + data).split(b'\n')
            self.pending[role] = parts.pop()
            for line in parts:
                self.states[role].feed(json.loads(line))

    def latch(self, exc):
        self.error = self.error or str(exc)
        path = self.directory / 'clock-invalid.json'
        try:
            with path.open('x', encoding='utf-8') as stream:
                json.dump(dict(error=self.error, status='INVALID_RUN', prior_samples_retained=True), stream)
        except FileExistsError:
            pass
        (self.directory / 'stop').touch(exist_ok=True)

    def loop(self):
        while not self.done.is_set():
            try:
                self.poll()
            except Exception as exc:
                self.latch(exc)
                return
            self.done.wait(.05)

    def start(self):
        if self.thread is not None:
            raise ClockInvalid('MONITOR_ALREADY_STARTED')
        self.thread = threading.Thread(target=self.loop, name='d29-clock-observer', daemon=True)
        self.thread.start()

    def check(self):
        if self.error:
            raise ClockInvalid(self.error)

    def close(self):
        self.done.set()
        if self.thread:
            self.thread.join(timeout=5)
            if self.thread.is_alive():
                self.latch(ClockInvalid('MONITOR_DID_NOT_STOP'))
        self.check()
        try:
            self.poll()
            if any(self.pending.values()):
                raise ClockInvalid('JOURNAL_PARTIAL_FINAL_LINE')
            return {role: state.finish() for role, state in self.states.items()}
        except Exception as exc:
            self.latch(exc)
            raise


def verify_host_cuts(before, after):
    """Record-ID window, not wall-time filtering (which a step can reverse)."""
    if before.get('error') or after.get('error'):
        raise ClockInvalid('HOST_EVENTS_UNAVAILABLE')
    watermark = before['last_record_id']
    if (after['last_record_id'] < watermark or after['oldest_record_id'] > watermark
            or after['after_record_id'] != watermark):
        raise ClockInvalid('HOST_EVENT_COVERAGE_LOST')
    for row in after['events']:
        if row['record_id'] <= watermark:
            raise ClockInvalid('HOST_EVENT_WINDOW_MISMATCH')
        if ((row['provider'] == 'Microsoft-Windows-Kernel-General' and row['id'] == 1)
                or (row['provider'] == 'Microsoft-Windows-Kernel-Power' and row['id'] in (42, 107))
                or row['provider'] == 'Microsoft-Windows-Power-Troubleshooter'):
            raise ClockInvalid('HOST_CLOCK_OR_SLEEP_EVENT')
    return dict(host_event_window_valid=True, physical_accreditation=False)
