from contextlib import ExitStack
from dataclasses import replace

import pytest

from cadence.poller import Poller
from cadence.store import Store
from test_engine import KEY, end, engine, start


def create(engine, **options):
    return engine.tool.handle({
        'action':'create', 'title':'Retest after restart',
        'note':'Retest the time tools and report results.',
        'trigger':{'kind':'startup'}, **options,
    }, session_id='sid')


def reopen(engine):
    path = engine.store.path
    engine.close()
    store = Store(path, engine.clock)
    return Poller(engine.ctx, store, engine.policy, engine.clock, session_key_fn=lambda: KEY,
                  paused=lambda: False, jitter=lambda: 0, compression_tip=lambda sid: sid)


@pytest.mark.parametrize('max_fires', [1, 2])
def test_startup_survives_restart_and_obeys_cap(engine, monkeypatch, max_fires):
    e = engine
    # Even the first poll acquiring its lock is not a startup for a new wake.
    birth = e.clock.now() - 60
    monkeypatch.setattr('cadence.poller.gateway_process_start', lambda: (f'startup:42:{birth}', birth))
    result = create(e, until={'max_fires':max_fires})
    assert result['armed'] and 'next gateway startup' in result['receipt']
    row, = e.tool.handle({'action':'list'}, session_id='sid')['wakes']
    assert row['next_check_at'] is None
    assert row['reason'] == 'Waiting for the next gateway startup.'
    wid = result['wake']['id']
    e.tick()
    assert not e.ctx.calls and not e.store.list_occurrences(wid)

    with ExitStack() as cleanup:
        for index in range(1, 4):
            e.clock.advance(3600)
            birth = e.clock.now()  # A new process may even reuse the old PID.
            e = reopen(e)
            cleanup.callback(e.store.close)
            cleanup.callback(e.close)
            e.ctx.runner.served = False
            e.tick()
            assert len(e.ctx.calls) == min(index - 1, max_fires)
            e.ctx.runner.served = True
            e.tick()
            if index <= max_fires:
                assert len(e.ctx.calls) == index
                start(e)
                end(e, 'progress', False)
            e.tick()
            e.release()
            e.tick()  # Reacquiring the profile, same process.
            assert len(e.ctx.calls) == min(index, max_fires)
            assert len(e.store.list_occurrences(wid)) == min(index, max_fires)
        assert e.store.get_wake(wid).status == 'done'


def test_startup_waits_for_token_and_retries_same_occurrence(engine, monkeypatch):
    e = engine
    e.policy = replace(e.policy, interruption_capacity=1, interruption_initial=0,
                       interruption_refill_seconds=300)
    birth = e.clock.now() - 30
    monkeypatch.setattr('cadence.poller.gateway_process_start', lambda: (f'startup:42:{birth}', birth))
    wid = create(e)['wake']['id']
    e.tick()
    e.clock.advance(1)
    birth = e.clock.now()
    e.release()
    e.tick()
    held, = e.store.list_occurrences(wid)
    assert held.error == 'held_interruptions' and not e.ctx.calls
    e.clock.advance(300)
    e.ctx.accept = False
    e.tick()
    rejected, = e.store.list_occurrences(wid)
    assert rejected.error == 'inject_failed'
    e.ctx.accept = True
    e.clock.advance(31)
    e.tick()
    start(e)
    end(e, 'progress', False)
    done, = e.store.list_occurrences(wid)
    assert done.dedupe_key == held.dedupe_key and done.state == 'done'
    assert e.store.get_wake(wid).status == 'active'


def test_startup_rejects_deadline_or_command(engine):
    for extra in ({'deadline':'in 1h'}, {'command':['date']}):
        assert 'error' in create(engine, trigger={'kind':'startup', **extra})


def test_retarget_pending_wake_waits_for_next_start_and_respects_expiry(engine, monkeypatch):
    e = engine
    birth = e.clock.now() - 60
    monkeypatch.setattr('cadence.poller.gateway_process_start', lambda: (f'startup:42:{birth}', birth))
    wid = create(e, trigger={'kind':'at','after':'10m'}, until={'expires':'in 20m'})['wake']['id']
    e.ctx.allowed = False
    e.clock.advance(600)
    e.tick()
    assert e.store.list_occurrences(wid)[0].state == 'pending'
    e.ctx.allowed = True
    updated = e.tool.handle({'action':'update','id':wid,'trigger':{'kind':'startup'}}, session_id='sid')
    assert updated['armed']
    e.release()
    e.tick()
    assert not e.ctx.calls
    assert e.store.list_occurrences(wid)[0].state == 'superseded'
    e.clock.advance(601)
    birth = e.clock.now()
    e.release()
    e.tick()
    assert not e.ctx.calls
    assert e.store.get_wake(wid).status == 'expired'
