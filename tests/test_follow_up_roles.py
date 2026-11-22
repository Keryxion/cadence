from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from threading import Barrier, local

import pytest

from cadence import follow_up
from cadence.intake import Flight
from test_engine import KEY, admit, arm, end, engine, pending, start


def owner(e, tid, text):
    admit(e, mid=tid, text=text)
    e.intake.pre_llm_call(session_id='sid', turn_id=tid, user_message=text, platform='telegram')


def call(e, args):
    return follow_up.handle(e.tool, args, session_id='sid')


@pytest.mark.parametrize('args', [{}, {'at':'14s'}, {'at':'15m1s'}, {'at':'30s','cancel':'x'}, {'at':30}])
def test_follow_up_rejects_invalid_arguments(engine,args):
    assert 'error' in call(engine,args)


def test_follow_up_cancel_and_context_chain(engine):
    e=engine
    owner(e,'original','Check my running build')
    wid=call(e,{'at':'15m'})['id']
    assert call(e,{'cancel':wid}) == call(e,{'cancel':wid}) == {'id':wid,'status':'cancelled'}
    timer=call(e,{'at':'15s'})['id']
    listed = e.tool.handle({'action':'list'}, session_id='sid')['wakes']
    assert all('continuation' not in w['trigger_json'] for w in listed)
    e.intake.on_session_end(session_id='sid',turn_id='original')
    owner(e,'intervening','Discuss dinner')
    e.intake.on_session_end(session_id='sid',turn_id='intervening')
    e.clock.advance(15)
    e.tick()
    context = start(e)
    assert 'Check my running build' in context['context'] and 'Discuss dinner' not in context['context']
    assert call(e,{'cancel':timer})['status']=='already_started'
    next_id=call(e,{'at':'15s'})['id']
    assert e.store.get_wake(next_id).trigger_json['continuation']['turn']=='original'
    assert e.intake.transform_llm_output(response_text='Build complete.',session_id='sid') is None
    e.intake.on_session_end(session_id='sid',turn_id='turn',completed=True)
    e.tick()
    assert len(e.ctx.calls)==1 and e.store.get_wake(timer).status=='done'


def test_verified_reminders_and_role_creation(engine):
    e=engine
    reminder=dict(action='create',trigger={'kind':'at','at':'in 20m'},note='Oven',owner_asked=True)
    assert 'error' in e.tool.handle(reminder,session_id='sid')
    owner(e,'owner','Remind me about the oven')
    assert e.tool.handle(reminder,session_id='sid')['armed']
    watcher=dict(action='create',note='Monitor work',trigger={'kind':'subagent_done'})
    assert e.tool.handle(watcher,session_id='sid')['error']=='role_required'
    assert e.tool.handle(dict(watcher,role=True),session_id='sid')['armed']
    for interval,accepted in [('59m',False),('1h',True)]:
        args=dict(watcher,role=True,trigger={'kind':'every','every':interval})
        assert bool(e.tool.handle(args,session_id='sid').get('armed')) == accepted


@pytest.mark.parametrize('kind',['every','cron','subagent_done'])
def test_one_hour_from_actual_start(engine,kind):
    e=engine
    w=arm(e,kind,role=True,last_fired_at=e.clock.now())
    o=pending(e,w,'e:due')
    e.clock.advance(3599)
    e.dispatch(o)
    assert not e.ctx.calls
    e.clock.advance(1)
    e.dispatch(e.store.get_occurrence(w.id,o.dedupe_key))
    start(e)
    assert len(e.ctx.calls)==1
    assert 'error' in call(e,{'at':'30s'})
    assert 'error' in e.tool.handle({'action':'respond','notify':False,'outcome':'progress','next_check':'59m'},session_id='sid')


def test_last_token_is_serialized_at_release(engine):
    e=engine
    e.policy=replace(e.policy,interruption_capacity=1)
    barrier=Barrier(2)
    def notify(sid):
        w=arm(e,'every',role=True)
        o=pending(e,w)
        assert e.store.claim(w.id,o.dedupe_key,epoch=e.epoch,pid=1)
        assert e.store.start(w.id,o.dedupe_key,attempt=1)
        e.intake.flights[sid]=Flight(KEY,sid,sid,w.id,o.dedupe_key,1)
        assert e.store.update_occurrence(w.id,o.dedupe_key,'started',attempt=1,notify=True,summary='Finding')
        barrier.wait()
        return e.intake.transform_llm_output(response_text='Finding',session_id=sid,turn_id=sid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(notify,('a','b')))
    assert results.count(None)==1 and results.count('[SILENT]')==1
    winner=('a','b')[results.index(None)]
    assert e.intake.transform_llm_output(response_text='Finding',session_id=winner)=='[SILENT]'
    assert e.interruption_tokens(KEY)==0 and e.interruption_tokens('other')==1
    e.clock.advance(299)
    assert e.interruption_tokens(KEY)==0
    e.clock.advance(1)
    assert e.interruption_tokens(KEY)==1 and not e.ctx.calls


def test_requested_deliveries_at_zero(engine):
    e=engine
    e.policy=replace(e.policy,interruption_capacity=1,interruption_refill_seconds=3600,wake_spacing_minutes=0)
    e.interruption_tokens(KEY,spend=True)
    owner(e,'original','Check the build and remind me about the oven')
    timer=call(e,{'at':'15s'})['id']
    reminder=e.tool.handle(dict(action='create',note='Oven',owner_asked=True,
        trigger={'kind':'at','at':'in 20m'}),session_id='sid')['wake']['id']
    e.intake.on_session_end(session_id='sid',turn_id='original')
    role=arm(e,'every',role=True)
    e.dispatch(pending(e,role))
    start(e)
    assert end(e,'progress',True,summary='Keep this finding')=='[SILENT]'
    assert e.store.get_wake(role.id).scratch=='Keep this finding'
    e.clock.advance(15)
    e.tick()
    start(e)
    assert e.intake.transform_llm_output(response_text='The build passed',session_id='sid') is None
    e.intake.on_session_end(session_id='sid',turn_id='turn',completed=True)
    assert e.store.list_occurrences(timer)[0].delivered
    e.clock.advance(1200)
    e.tick()
    start(e)
    assert end(e,'done',True,summary='Oven') != '[SILENT]'
    assert e.store.list_occurrences(reminder)[0].delivered and e.interruption_tokens(KEY)==0


def test_unresolvable_follow_up_is_recorded_without_injection(engine):
    e = engine
    owner(e,'first','Check the build')
    timer = call(e,{'at':'30s'})['id']
    e.intake.on_session_end(session_id='sid',turn_id='first')
    from test_engine import session
    session(e,current_session_id='replacement')
    e.clock.advance(30)
    e.tick()
    assert not e.ctx.calls
    assert e.store.get_wake(timer).status_reason == 'skipped:continuation_context_missing'


def test_duplicates_and_failures_preserve_tokens(engine):
    e = engine
    e.policy = replace(e.policy, interruption_capacity=2,interruption_refill_seconds=86400)
    role = arm(e,'self',role=True)
    e.dispatch(pending(e,role,'first'))
    start(e)
    assert end(e,'progress',True,summary='Finding') is None
    assert e.interruption_tokens(KEY) == 1
    e.clock.advance(3600)
    e.dispatch(pending(e,role,'duplicate'))
    start(e)
    assert end(e,'progress',True,summary='Finding') == '[SILENT]'
    assert e.interruption_tokens(KEY) == 1
    e.clock.advance(3600)
    e.dispatch(pending(e,role,'failure'))
    start(e)
    e.intake.on_session_end(session_id='sid',turn_id='turn',failed=True)
    assert e.interruption_tokens(KEY) == 1


def test_refill_does_not_start_an_early_role_watcher(engine):
    e = engine
    e.policy = replace(e.policy, interruption_capacity=1)
    e.interruption_tokens(KEY,spend=True)
    role = arm(e,'subagent_done',role=True,last_fired_at=e.clock.now())
    for i in range(2):
        key = f'match:{i}'
        e.store.add_occurrence(role.id,key,payload=[{'finding': i}])
        e.dispatch(e.store.get_occurrence(role.id,key))
    held, = e.store.list_occurrences(role.id,state='pending')
    assert held.held_matches == 2 and held.payload_json == [{'finding': 1}]
    e.clock.advance(300)
    e.tick()
    assert e.interruption_tokens(KEY) == 1 and not e.ctx.calls
    e.clock.advance(3300)
    e.tick()
    assert len(e.ctx.calls) == 1 and '"finding": 1' in e.ctx.calls[0][0]


def test_registered_follow_up_returns_only_the_timer_id(engine,monkeypatch):
    import json
    from cadence.registration import Runtime, register
    monkeypatch.setattr(Runtime,'start',lambda self: None)
    runtime = register(engine.ctx,clock=engine.clock)
    runtime._engine = engine
    try:
        owner(engine,'owner','Check the running build')
        handler = engine.ctx.tools['follow_up']['handler']
        result = json.loads(handler({'at':'30s'},session_id='sid'))
        assert set(result) == {'id'}
        assert json.loads(handler({'cancel':result['id']},session_id='sid'))['status']=='cancelled'
    finally:
        runtime._engine = None
        runtime.close()


def test_concurrent_role_triggers_start_only_one_occurrence(engine, monkeypatch):
    role = arm(engine, 'every', role=True, last_fired_at=engine.clock.now()-3600)
    triggers = [pending(engine, role, key) for key in ('first', 'second')]
    eligible = Barrier(2)
    original = engine.gate
    worker = local()

    def simultaneous_check(wake, occurrence, session):
        result = original(wake, occurrence, session)
        if not getattr(worker, "checked", False):
            worker.checked = True
            eligible.wait(timeout=5)
        return result

    monkeypatch.setattr(engine, 'gate', simultaneous_check)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(engine.dispatch, triggers))
    assert len(engine.ctx.calls) == 1
    start(engine)
    assert engine.store.get_wake(role.id).fires == 1


def test_failed_finalization_after_release_retains_charge(engine):
    role = arm(engine, 'every', role=True)
    occurrence = pending(engine, role)
    engine.dispatch(occurrence)
    start(engine)
    engine.tool.handle(dict(action='respond', outcome='progress', notify=True, summary='Finding'), session_id='sid')
    balance = engine.interruption_tokens(KEY)
    assert engine.intake.transform_llm_output(response_text='Finding', session_id='sid') is None
    engine.intake.on_session_end(session_id='sid', turn_id='turn', failed=True)
    assert engine.store.get_meta('admitted:'+occurrence.id) == 'adapter outcome unknown'
    assert engine.interruption_tokens(KEY) == balance-1
    assert engine.store.get_occurrence(role.id, occurrence.dedupe_key).state == 'interrupted'


def test_session_reset_revokes_owner_turn_authority(engine):
    owner(engine, 'original', 'Remind me about the oven')
    engine.intake.on_session_reset(old_session_id='sid', new_session_id='new')
    assert 'error' in call(engine, {'at': '30s'})
    result = engine.tool.handle(dict(action='create', note='Oven', owner_asked=True,
                                     trigger={'kind':'at', 'at':'in 20m'}), session_id='sid')
    assert result['error'] == 'verified_owner_reminder_required'
