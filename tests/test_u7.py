"""U7 regressions: synthetic gateway sessions, no model or network calls."""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from cadence import commands
from cadence.schedule import local_day
from test_engine import engine, arm, start, end, session, KEY
from test_commands import runtime
import test_bench_mutants as mutants


@pytest.mark.parametrize('urgent', [False, True])
def test_R7_L5_owner_wake_exempt_from_unanswered(engine, urgent):
    e = engine
    session(e, unanswered_count=e.policy.max_unanswered)
    w = arm(e, creator='user', urgent=urgent)
    e.tick()
    assert len(e.ctx.calls) == 1
    start(e)
    assert end(e, outcome='done', notify=True) is None
    assert e.store.list_occurrences(w.id)[0].delivered
    assert e.store.get_wake(w.id).status == 'done'


@pytest.mark.parametrize('reason', ['unanswered', 'interruption_limit'])
def test_R7_L5_dispatch_skip_terminal_one_shot(runtime, reason):
    e = runtime.get_engine()
    if reason == 'unanswered':
        session(e, unanswered_count=e.policy.max_unanswered)
    else:
        e.policy = replace(e.policy, interruption_capacity=0)
    w = arm(e, creator='agent')
    e.tick()
    o, = e.store.list_occurrences(w.id)
    assert o.state == 'skipped' and o.error == reason
    current = e.store.get_wake(w.id)
    assert current.status == 'failed' and current.status_reason == 'skipped:' + reason
    assert current.next_due_at is None and not e.ctx.calls
    assert current.status_reason in commands.handle('list', runtime)
    assert current.status_reason in commands.handle('why ' + w.id, runtime)


def test_R7_L5_builtin_checkin_stays_muted(engine):
    e = engine
    e.policy = replace(e.policy, owner_silent_checkin=True)
    session(e, unanswered_count=e.policy.max_unanswered,
            last_human_at=e.clock.now() - 2 * 86400)
    e.tick()
    w, = e.store.list_wakes()
    assert w.creator == 'user' and w.trigger_json['builtin']
    o, = e.store.list_occurrences(w.id)
    assert o.state == 'skipped' and o.error == 'unanswered'
    assert not e.ctx.calls


@pytest.mark.parametrize('gate', ['interruption_limit',
                                   'busy', 'provider_unavailable'])
def test_R7_L5_owner_obeys_other_gates(engine, gate):
    e = engine
    e.acquire()  # Startup reconciliation clears stale busy flags first.
    session(e, unanswered_count=e.policy.max_unanswered)
    if gate == 'interruption_limit':
        e.policy = replace(e.policy, interruption_capacity=0)
    elif gate == 'busy':
        session(e, busy_since=e.clock.now())
    else:
        e.provider_failure('rate_limit')
    w = arm(e, 'every' if gate == 'interruption_limit' else 'at', creator='user')
    e.tick()
    o, = e.store.list_occurrences(w.id)
    assert o.error == gate and not e.ctx.calls




@pytest.mark.parametrize('drop', ['unanswered', 'interruption_limit'])
@pytest.mark.parametrize('window', ['session_paused', 'provider_unavailable'])
def test_R7_L6_windows_before_dropping_gates(engine, window, drop):
    e = engine
    if drop == 'unanswered':
        session(e, unanswered_count=e.policy.max_unanswered)
    else:
        e.policy = replace(e.policy, interruption_capacity=0)
    until = e.clock.now() + 300
    if window == 'session_paused':
        session(e, paused_until=until)
    elif window == 'provider_unavailable':
        e.provider_failure('rate_limit')
    else:
        # Exercise the configured range separately from the command override.
        from datetime import datetime, timezone
        e.clock.wall = datetime(2026, 10, 12, 22, 0, tzinfo=timezone.utc).timestamp()
        session(e, last_human_at=e.clock.now(), last_activity_at=e.clock.now())
        e.policy = replace(e.policy)
        until = e.clock.now() + 300
    w = arm(e, creator='agent')
    e.tick()
    o, = e.store.list_occurrences(w.id)
    assert o.state == 'pending' and o.error == window and not e.ctx.calls
    e.clock.advance(until - e.clock.now())
    e.tick()
    current = e.store.get_occurrence(w.id, o.dedupe_key)
    assert current.state == 'skipped' and current.error == drop


@pytest.mark.parametrize('elapsed', [59, 60])
def test_R7_CI1_module_total_budget(monkeypatch, elapsed):
    stamps = iter([100, 100 + elapsed])
    monkeypatch.setattr(mutants.time, 'monotonic', lambda: next(stamps))
    fixture = mutants.mutant_budget
    marker = getattr(fixture, '_fixture_function_marker', None) or fixture._pytestfixturefunction
    assert marker.scope == 'module' and marker.autouse
    timer = fixture.__wrapped__()
    next(timer)
    if elapsed < 60:
        with pytest.raises(StopIteration):
            next(timer)
    else:
        with pytest.raises(AssertionError, match='60 s in total'):
            next(timer)


def test_R7_CI1_no_per_mutant_clock_limit(monkeypatch, tmp_path):
    clock = [100]
    monkeypatch.setattr(mutants.time, 'monotonic', lambda: clock[0])
    def result(*args):
        clock[0] += 3
        return {'scenario': ['caught']}
    monkeypatch.setattr(mutants, 'scratch_run', result)
    mutants.test_R6_E1_E2_E3_mutant_gate(tmp_path, 'replay_slots', {})


@pytest.mark.parametrize('path', ['SECURITY.md', 'skills/cadence-usage/SKILL.md'])
def test_R7_COST_full_context_disclosure(path):
    text = (Path(__file__).resolve().parents[1] / path).read_text()
    for phrase in ('normal model turn', "conversation's context size", 'billed like one', '/cadence status'):
        assert phrase in text,(path,phrase)
    assert 'cost' in text and 'unpriced' in text



def test_R7_COST_ledger_tokens_per_wake(runtime):
    e = runtime.get_engine()
    wakes = [arm(e, title='first'), arm(e, title='second')]
    day = local_day(e.clock.now(), e.policy.resolved_timezone())
    for w, tokens in zip(wakes, [110000, 209000]):
        e.store.add_ledger(day, w.id, tokens_in=tokens, tokens_out=50)
    out = commands.handle('ledger', runtime)
    assert 'in / cached / written / out' in out
    for w, tokens in zip(wakes, [110000, 209000]):
        line, = [line for line in out.splitlines() if line.startswith(w.id)]
        assert f'{tokens} / 0 / 0 / 50' in line
    status = commands.handle('status', runtime)
    assert 'Today' in status and '319000 / 0 / 0 / 100' in status
