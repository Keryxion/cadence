"""U9 wording and claim bookkeeping regressions; synthetic gateway only."""
import pytest

from test_engine import engine, arm, start, end
from test_wake_text import records
from cadence.wake_text import render_wake


HOLDS = [
    ('busy', 'a busy chat'),
    ('wake_spacing', 'wake spacing'),
    ('in_flight', 'another wake in flight'),
    ('session_paused', 'a pause'),
    ('provider_unavailable', 'a provider outage'),
    ('not_before', 'an error backoff'),
]


@pytest.mark.parametrize('reason,label', HOLDS)
@pytest.mark.parametrize('recovered', [False, True])
def test_R9_W1_dispatch_hold_label(engine, reason, label, recovered):
    e = engine
    e.acquire()
    w = arm(e, next_due_at=None)
    key = f't:{e.clock.now()-120:.17g}'
    e.store.add_occurrence(w.id, key)
    e.store.update_occurrence(w.id, key, 'pending', error=reason)
    o = e.store.get_occurrence(w.id, key)
    if recovered:
        e.store.set_meta('recovered:'+o.id, '1')
    e.dispatch(o)
    text, _ = e.ctx.calls[-1]
    suffix = " after_restart='true'" if recovered else ''
    assert f"delayed_by='{reason}'{suffix}" in text
    assert 'late by' not in text
    assert ('after_restart=' in text) == recovered


@pytest.mark.parametrize('reason', ['', 'ack_timeout', 'injection_disabled'])
@pytest.mark.parametrize('recovered', [False, True])
def test_R9_W1_no_designed_hold_still_late(engine, reason, recovered):
    e = engine
    e.acquire()
    w = arm(e, next_due_at=None)
    key = f't:{e.clock.now()-120:.17g}'
    e.store.add_occurrence(w.id, key)
    e.store.update_occurrence(w.id, key, 'pending', error=reason)
    o = e.store.get_occurrence(w.id, key)
    if recovered:
        e.store.set_meta('recovered:'+o.id, '1')
    e.dispatch(o)
    suffix = " after_restart='true'" if recovered else ''
    assert "late_by='2m'" + suffix in e.ctx.calls[-1][0]


@pytest.mark.parametrize('seconds,expected', [(59, ''),
                                             (60, "late_by='1m'")])
def test_R9_W1_late_threshold(clock, seconds, expected):
    w, o, s = records(clock)
    text = render_wake(w, o, s, clock=clock, late_by_s=seconds)
    assert ('late_by=' in text.splitlines()[0]) == bool(expected)
    assert expected in text.splitlines()[0]


@pytest.mark.parametrize('reason,label', HOLDS)
def test_R9_W2_claim_clears_error_and_done_stays_clear(engine, reason, label):
    e = engine
    e.acquire()
    w = arm(e, next_due_at=None)
    key = f't:{e.clock.now()-120:.17g}'
    e.store.add_occurrence(w.id, key)
    e.store.update_occurrence(w.id, key, 'pending', error=reason)
    e.dispatch(e.store.get_occurrence(w.id, key))
    claimed = e.store.get_occurrence(w.id, key)
    assert claimed.state == 'claimed' and claimed.error == ''
    assert f"delayed_by='{reason}'" in e.ctx.calls[-1][0]
    start(e)
    assert end(e, outcome='done', notify=True) is None  # Leave the gateway reply unchanged.
    done = e.store.get_occurrence(w.id, key)
    assert done.state == 'done' and done.error == ''


def test_R9_W2_failed_claim_preserves_error(engine):
    e = engine
    w = arm(e, next_due_at=None)
    e.store.add_occurrence(w.id, 'terminal')
    e.store.cas_occurrence(w.id, 'terminal', 'pending', 'skipped', error='quiet_hours')
    assert not e.store.claim(w.id, 'terminal', epoch=e.epoch, pid=1)
    assert e.store.get_occurrence(w.id, 'terminal').error == 'quiet_hours'
