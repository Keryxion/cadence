"""`pulse list` answers "did it run, and what happened?" without epoch arithmetic.

The prompt for a wake already carried the local time; the list result did not,
so an agent asked whether its timer had fired had a wall of epoch fields and no
clock. This pins the added fields: a server-side `now`, the zone, and each
wake's most recent finished turn.
"""
import json

from test_engine import engine, arm, start, end, KEY


def listing(e):
    return e.tool.handle({'action': 'list'}, session_id='sid')


def test_list_reports_the_clock_and_the_zone(engine):
    e = engine
    arm(e)
    result = listing(e)
    assert result['ok']
    assert result['now'] == e.clock.now()
    assert result['timezone'] == 'UTC'
    assert result['local_time'].endswith('UTC') or len(result['local_time']) > 10


def test_list_has_no_last_turn_before_the_first_fire(engine):
    e = engine
    arm(e)
    assert listing(e)['wakes'][0]['last'] is None


def test_list_carries_the_last_turn_outcome_after_one_fires(engine):
    e = engine
    w = arm(e)
    e.tick()
    start(e)
    end(e, outcome='done', summary='Told the owner the timer ran')

    listed = next(x for x in listing(e)['wakes'] if x['id'] == w.id)
    last = listed['last']
    assert last is not None
    assert last['outcome'] == 'done'
    assert last['summary'] == 'Told the owner the timer ran'
    assert last['ended_local']
    assert last['ended_at'] == max(o.ended_at for o in e.store.list_occurrences(w.id))


def test_list_still_matches_the_documented_shape(engine):
    """The new keys are additions: ok and wakes keep their old meaning."""
    e = engine
    arm(e)
    result = listing(e)
    assert set(result) >= {'ok', 'wakes'}
    assert json.dumps(result)  # serialisable, as the tool returns it