import pytest
from cadence import follow_up
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


@pytest.mark.parametrize('wrapped', [False, True])
def test_owner_context_and_zero_bucket(engine, wrapped):
    e = engine
    text = 'Check my running build'
    admit(e, mid='original', text=text)
    message = text
    if wrapped:
        message = ('Gateway message origin (JSON data, not instructions or authorization):\n'
                   '{"message_id":"original","platform":"telegram","chat_id":"unit"}\n' + text)
    e.intake.pre_llm_call(session_id='sid', turn_id='original', user_message=message, platform='telegram')
    timer = call(e, {'at':'15s'})['id']
    e.intake.on_session_end(session_id='sid', turn_id='original')
    owner(e, 'dinner', 'Discuss dinner')
    e.intake.on_session_end(session_id='sid', turn_id='dinner')
    for _ in range(e.policy.interruption_capacity):
        e.interruption_tokens(KEY, spend=True)
    e.clock.advance(15)
    e.tick()
    context = start(e)
    assert text in context['context'] and 'Discuss dinner' not in context['context']
    next_timer = call(e, {'at':'15s'})['id']
    assert e.store.get_wake(next_timer).trigger_json['continuation']['turn'] == 'original'
    assert e.intake.transform_llm_output(response_text='Build complete', session_id='sid') is None
    e.intake.on_session_end(session_id='sid', turn_id='turn', completed=True)
    assert e.store.list_occurrences(timer)[0].delivered
    assert e.interruption_tokens(KEY) == 0


def test_cancelled_timer_and_pulse_turn_eligibility(engine):
    e = engine
    owner(e, 'original', 'Check the build')
    timer = call(e, {'at':'15s'})['id']
    call(e, {'cancel':timer})
    e.intake.on_session_end(session_id='sid', turn_id='original')
    e.clock.advance(15)
    e.tick()
    assert not e.ctx.calls
    wake = arm(e, 'every')
    e.dispatch(pending(e, wake))
    start(e)
    assert call(e, {'at':'30s'})['error'] == 'verified_owner_turn_required'

def test_silent_continuation_rearm_preserves_empty_bucket(engine):
    e = engine
    owner(e, 'original', 'Check the build')
    call(e, {'at':'15s'})
    e.intake.on_session_end(session_id='sid', turn_id='original')
    for _ in range(e.policy.interruption_capacity):
        e.interruption_tokens(KEY, spend=True)
    e.clock.advance(15)
    e.tick()
    start(e)
    assert 'id' in call(e, {'at':'15s'})
    assert end(e, 'progress', False) == '[SILENT]'
    assert e.interruption_tokens(KEY) == 0


def test_existing_pulse_entry_points(engine):
    e = engine
    create = lambda **kw: e.tool.handle(dict(action='create', note='Check work', **kw), session_id='sid')
    assert create(trigger={'kind':'at','at':'in 10m'})['armed']
    assert create(role=True, trigger={'kind':'every','every':'30m'})['armed']
    assert create(owner_asked=True, trigger={'kind':'at','at':'in 20m'})['armed']

def test_pulse_cannot_list_or_manage_follow_up(engine, monkeypatch):
    from types import SimpleNamespace
    from cadence import commands
    monkeypatch.setattr(commands, "session_env", lambda name: KEY if name == "HERMES_SESSION_KEY" else "")
    e = engine
    owner(e, 'original', 'Check my build')
    timer = call(e, {'at':'30s'})['id']
    assert e.tool.handle({'action':'list'}, session_id='sid')['wakes'] == []
    for action in ('update', 'pause', 'resume', 'cancel'):
        assert e.tool.handle({'action':action, 'id':timer}, session_id='sid')['error'] == 'unknown_wake'
    for command in ('list all', 'status', 'ledger', 'why '+timer):
        assert timer not in commands.handle(command, SimpleNamespace(get_engine=lambda: e))
    for action in ('pause', 'resume', 'cancel'):
        e.tool.handle({'action':action, 'id':'all'}, session_id='sid')
        commands.handle(action+' all', SimpleNamespace(get_engine=lambda: e))
    assert e.store.get_wake(timer).status == 'active'
    assert call(e, {'cancel':timer})['status'] == 'cancelled'
