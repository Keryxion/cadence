from dataclasses import replace

from cadence.poller import Poller
from test_engine import KEY, arm, end, engine, pending, start


def test_initially_empty_bucket_refills_without_spending(engine):
    e = engine
    e.policy = replace(e.policy, interruption_initial=0)
    assert e.interruption_tokens(KEY) == 0
    e.clock.advance(300)
    assert e.interruption_tokens(KEY) == 1
    e.clock.advance(600)
    assert e.interruption_tokens(KEY) == 3
    e.clock.advance(6000)
    assert e.interruption_tokens(KEY) == 15


def test_watcher_waits_for_first_token_from_initially_empty_bucket(engine):
    e = engine
    e.policy = replace(e.policy, interruption_initial=0)
    watcher = arm(e, 'subagent_done')
    occurrence = pending(e, watcher, 'e:first')
    e.dispatch(occurrence)
    assert not e.ctx.calls
    e.clock.advance(299)
    e.dispatch(e.store.get_occurrence(watcher.id, occurrence.dedupe_key))
    assert not e.ctx.calls
    e.clock.advance(1)
    e.dispatch(e.store.get_occurrence(watcher.id, occurrence.dedupe_key))
    assert len(e.ctx.calls) == 1
    start(e)
    end(e, 'progress', True)
    assert e.interruption_tokens(KEY) == 0


def test_refill_preserves_partial_interval_and_discards_overflow(engine):
    e = engine
    e.policy = replace(e.policy, interruption_capacity=2, interruption_refill_seconds=10)
    assert e.interruption_tokens(KEY) == 2
    e.interruption_tokens(KEY, spend=True)
    e.clock.advance(6)
    e.interruption_tokens(KEY, spend=True)
    assert e.interruption_tokens(KEY) == 0
    assert e.interruption_tokens('another-chat') == 2
    e.clock.advance(4)
    assert e.interruption_tokens(KEY) == 1
    e.clock.advance(99)
    assert e.interruption_tokens(KEY) == 2
    e.interruption_tokens(KEY, spend=True)
    e.clock.advance(9)
    assert e.interruption_tokens(KEY) == 1
    restarted = Poller(e.ctx, e.store, e.policy, e.clock)
    assert restarted.interruption_tokens(KEY) == 2


def test_delivered_watcher_uses_shared_token_and_held_matches_merge(engine):
    e = engine
    e.policy = replace(e.policy, interruption_capacity=1, wake_spacing_minutes=0)
    watcher = arm(e, 'subagent_done')
    e.dispatch(pending(e, watcher, 'e:first'))
    start(e)
    end(e, 'progress', True)
    assert e.interruption_tokens(KEY) == 0
    timer = arm(e)
    assert e.gate(timer, pending(e, timer), e.store.get_session(KEY))[0] == 'interruption_limit'
    held = pending(e, watcher, 'e:second')
    e.dispatch(held)
    e.dispatch(pending(e, watcher, 'e:third'))
    remaining, = e.store.list_occurrences(watcher.id, state='pending')
    assert remaining.held_reason == 'held_interruptions' and remaining.held_matches == 2
    e.clock.advance(300)
    e.dispatch(remaining)
    start(e)
    end(e, 'progress', False)
    assert e.interruption_tokens(KEY) == 1
