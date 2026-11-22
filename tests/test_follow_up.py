import pytest
from cadence import follow_up
from test_engine import KEY, admit, arm, end, engine, pending, start as start_wake

def start(e, history=None):
    text = e.ctx.calls[-1][0]
    if text.startswith("[follow_up id='"):
        return e.intake.pre_llm_call(session_id='sid', turn_id='turn', user_message=text, platform='telegram',
            conversation_history=history or [{'role':'user','content':text,'display_kind':'internal_notification'}])
    return start_wake(e)


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
    history = [
        {'role':'user','content':'Check my running build'},
        {'role':'user','content':'Discuss dinner'},
        {'role':'user','content':e.ctx.calls[-1][0],'display_kind':'internal_notification'}]
    expected_history = [dict(row) for row in history]
    context = start(e, history)
    assert context is None
    assert history == expected_history
    assert e.ctx.calls[-1][0].startswith("[follow_up id='")
    assert 'text' not in e.store.get_wake(timer).trigger_json['continuation']
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


def test_registered_follow_up_returns_armed_receipt(engine,monkeypatch):
    from datetime import datetime
    import json
    from cadence.registration import Runtime, register
    monkeypatch.setattr(Runtime,'start',lambda self: None)
    runtime = register(engine.ctx,clock=engine.clock)
    runtime._engine = engine
    try:
        owner(engine,'owner','Check the running build')
        handler = engine.ctx.tools['follow_up']['handler']
        result = json.loads(handler({'at':'30s'},session_id='sid'))
        assert set(result) == {'id', 'armed', 'due_at'}
        assert result['armed'] is True
        due = datetime.fromisoformat(result['due_at'])
        assert due.utcoffset().total_seconds() == 0
        assert due.timestamp() == engine.clock.now()+30
        assert due.timestamp() == engine.store.get_wake(result['id']).next_due_at
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
    assert context is None
    assert e.ctx.calls[-1][0].startswith("[follow_up id='")
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

def test_busy_timer_is_consumed_and_new_orphans_other_timers(engine):
    e = engine
    owner(e, 'original', 'Check the build')
    first = call(e, {'at':'30s'})['id']
    second = call(e, {'at':'1m30s'})['id']
    assert first != second and e.store.get_wake(first).status == 'active'
    e.clock.advance(30)
    e.tick()
    assert not e.ctx.calls
    assert e.store.list_occurrences(first)[0].error == 'continuation_busy'
    assert e.store.list_occurrences(first)[0].state == 'skipped'
    assert e.store.get_wake(first).status == 'done'
    e.intake.on_session_end(session_id='sid', turn_id='original')
    e.tick()
    assert not e.ctx.calls
    e.intake.on_session_reset(old_session_id='sid', new_session_id='new')
    assert e.store.get_wake(second).status == 'orphaned'
    e.clock.advance(90)
    e.tick()
    assert not e.ctx.calls

def test_armed_timer_survives_runtime_restart(engine):
    from cadence.poller import Poller
    e = engine
    owner(e, 'original', 'Check my running build')
    timer = call(e, {'at':'30s'})['id']
    e.intake.on_session_end(session_id='sid', turn_id='original')
    e.close()
    restarted = Poller(e.ctx, e.store, e.policy, e.clock, session_key_fn=lambda: KEY,
                       paused=lambda: False, jitter=lambda: 0, compression_tip=lambda sid: sid)
    try:
        e.clock.advance(30)
        restarted.tick()
        assert len(e.ctx.calls) == 1
        context = start(restarted)
        assert context is None
        assert e.ctx.calls[-1][0].startswith("[follow_up id='")
        assert restarted.store.get_wake(timer).fires == 1
    finally:
        restarted.close()

def test_plain_signal_text_from_owner_cannot_claim_timer(engine):
    e = engine
    owner(e, 'original', 'Check the build')
    timer = call(e, {'at':'15s'})['id']
    e.intake.on_session_end(session_id='sid', turn_id='original')
    e.clock.advance(15)
    e.tick()
    owner(e, 'spoof', 'Follow-up fired')
    assert e.store.get_wake(timer).fires == 0
    assert not e.intake.flights


def test_existing_timer_request_snapshot_is_ignored(engine):
    e = engine
    owner(e, 'original', 'Old task')
    timer = call(e, {'at':'15s'})['id']
    wake = e.store.get_wake(timer)
    trigger = {**wake.trigger_json, 'continuation': {
        **wake.trigger_json['continuation'], 'text':'Old task'}}
    e.store.cas_wake(timer, 'active', expected_version=wake.version, trigger_json=trigger)
    e.intake.on_session_end(session_id='sid', turn_id='original')
    e.clock.advance(15)
    e.tick()
    assert start(e) is None
    assert e.ctx.calls[-1][0].startswith("[follow_up id='")

def test_owner_correction_does_not_require_exact_message_text(engine):
    e = engine
    owner(e, 'first', 'Check the build')
    e.intake.on_session_end(session_id='sid', turn_id='first', interrupted=True)
    admit(e, mid='correction', text='Check again')
    e.intake.pre_llm_call(session_id='sid', turn_id='correction', platform='telegram',
                         user_message='[Owner correction]\nCheck again\n[Response interrupted]')
    assert call(e, {'at':'30s'})['armed'] is True


def test_owner_correction_in_current_turn_can_arm_follow_up(engine):
    e = engine
    owner(e, 'first', 'Check the build')
    e.intake.on_session_end(session_id='sid', turn_id='first')
    # Runtime starts an owner turn without the optional ingress observer.
    e.intake.pre_llm_call(session_id='sid', turn_id='correction', platform='telegram',
                         user_message='Gateway-wrapped correction', conversation_history=[
                             {'role':'user','content':'Check again','platform_message_id':'correction'}])
    assert call(e, {'at':'30s'})['armed'] is True

def test_owner_correction_folded_into_pulse_is_verified_by_runtime(engine):
    from test_engine import fold
    e = engine
    wake = arm(e, 'every', role=True)
    e.dispatch(pending(e, wake))
    start(e)
    assert call(e, {'at':'30s'})['error'] == 'verified_owner_turn_required'
    fold(e, mid='correction', text='Follow up on my correction in 30 seconds')
    assert call(e, {'at':'30s'})['armed'] is True


def test_old_turn_cleanup_does_not_revoke_current_correction(engine):
    e = engine
    owner(e, 'first', 'Check the build')
    owner(e, 'correction', 'Check again')
    e.intake.on_session_end(session_id='sid', turn_id='first', interrupted=True)
    assert call(e, {'at':'30s'})['armed'] is True
    e.intake.on_session_end(session_id='sid', turn_id='correction')
    assert call(e, {'at':'30s'})['error'] == 'verified_owner_turn_required'


def test_bot_message_cannot_supply_owner_authority(engine):
    e = engine
    e.store.set_meta('nonhuman:'+KEY+':bot-message', '1')
    e.intake.pre_llm_call(session_id='sid', turn_id='bot', platform='telegram', user_message='Check again',
        conversation_history=[{'role':'user','content':'Check again','platform_message_id':'bot-message'}])
    assert call(e, {'at':'30s'})['error'] == 'verified_owner_turn_required'


def test_gateway_worker_acknowledges_follow_up_after_intervening_turn(engine):
    from cadence.poller import Poller
    from cadence.store import Store

    e = engine
    owner(e, 'original', 'Check the build')
    timer = call(e, {'at': '30s'})['id']
    e.intake.on_session_end(session_id='sid', turn_id='original')
    e.clock.advance(30)
    e.tick()
    signal = e.ctx.calls[-1][0]
    assert e.store.list_occurrences(timer)[0].state == 'claimed'

    # The gateway can run the queued turn with its own plugin instance.
    store = Store(e.store.path, e.clock)
    worker = Poller(e.ctx, store, e.policy, e.clock, session_key_fn=lambda: KEY,
                    paused=lambda: False, jitter=lambda: 0, compression_tip=lambda sid: sid)
    try:
        owner(worker, 'intervening', signal)
        worker.intake.on_session_end(session_id='sid', turn_id='intervening')
        assert e.store.list_occurrences(timer)[0].state == 'claimed'
        start(worker)
        assert e.store.list_occurrences(timer)[0].state == 'started'
        worker.intake.transform_llm_output(response_text='Finished', session_id='sid')
        worker.intake.on_session_end(session_id='sid', turn_id='turn', completed=True)
        assert e.store.list_occurrences(timer)[0].delivered
        e.clock.advance(601)
        e.tick()
        assert len(e.ctx.calls) == 1
    finally:
        worker.close()
        store.close()
