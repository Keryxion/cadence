from dataclasses import replace

import pytest

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


@pytest.mark.parametrize('acquired', [False, True])
def test_gateway_worker_delivery_debits_next_scheduler_admission(engine, acquired):
    from cadence.store import Store
    from test_follow_up import owner, call, start as start_follow_up

    scheduler = engine
    scheduler.policy = replace(scheduler.policy, interruption_capacity=1, wake_spacing_minutes=0, max_unanswered=10)
    if acquired:
        scheduler.tick()
    with Store(scheduler.store.path, scheduler.clock) as worker_store:
        worker = Poller(scheduler.ctx, worker_store, scheduler.policy, scheduler.clock,
                        session_key_fn=lambda: KEY, paused=lambda: False)
        try:
            owner(worker, 'owner', 'Check again')
            timer = call(worker, {'at':'15s'})['id']
            worker.intake.on_session_end(session_id='sid', turn_id='owner')
            first = arm(scheduler)
            scheduler.dispatch(pending(scheduler, first))
            start(worker)
            end(worker, 'progress', True)
            assert scheduler.store.list_occurrences(first.id)[0].delivered
            assert scheduler.interruption_tokens(KEY) == 0
            second = arm(scheduler, 'subagent_done')
            held = pending(scheduler, second, 'e:second')
            scheduler.dispatch(held)
            assert scheduler.store.get_occurrence(second.id, held.dedupe_key).error == 'held_interruptions'
            scheduler.clock.advance(15)
            scheduler.tick()
            start_follow_up(worker)
            worker.intake.transform_llm_output(response_text='Requested update', session_id='sid')
            worker.intake.on_session_end(session_id='sid', turn_id='turn', completed=True)
            assert scheduler.store.list_occurrences(timer)[0].delivered
            assert scheduler.interruption_tokens(KEY) == 0
            scheduler.clock.advance(284)
            assert scheduler.interruption_tokens(KEY) == 0
            scheduler.clock.advance(1)
            assert scheduler.interruption_tokens(KEY) == 1
            scheduler.dispatch(scheduler.store.get_occurrence(second.id, held.dedupe_key))
            start(worker)
            end(worker, 'progress', True)
            assert scheduler.store.get_occurrence(second.id, held.dedupe_key).delivered
            assert scheduler.interruption_tokens(KEY) == 0
        finally:
            worker.close()


def _finish_in_gateway_worker(path, clock, marker):
    from cadence.policy import Policy
    from cadence.store import Store
    from test_engine import GatewayCtx

    with Store(path, clock) as store:
        worker = Poller(GatewayCtx(path.parent), store,
                        Policy(clock=clock, interruption_capacity=1), clock,
                        session_key_fn=lambda: KEY, paused=lambda: False)
        try:
            start(worker, message=marker)
            end(worker, 'progress', True)
            assert not worker.interruption_buckets
        finally:
            worker.close()


def test_separate_process_delivery_refills_from_completion_instant(engine, monkeypatch):
    import multiprocessing
    from pathlib import Path

    # Both the checkout directory on CI and the plugin package are named cadence.
    # Make the spawned interpreter resolve the inner package just as pytest does.
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))

    engine.policy = replace(engine.policy, interruption_capacity=1)
    wake = arm(engine)
    engine.tick()
    child = multiprocessing.get_context('spawn').Process(target=_finish_in_gateway_worker,
        args=(engine.store.path, engine.clock, engine.ctx.calls[-1][0]))
    child.start()
    try:
        child.join(timeout=30)
        assert child.exitcode == 0
    finally:
        if child.is_alive():
            child.terminate()
            child.join()
    assert engine.store.list_occurrences(wake.id)[0].delivered
    engine.clock.advance(299)
    assert engine.interruption_tokens(KEY) == 0
    assert engine.interruption_tokens('other-chat') == 1
    engine.clock.advance(1)
    assert engine.interruption_tokens(KEY) == 1
