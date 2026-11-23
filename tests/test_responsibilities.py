"""Public responsibility/trigger contracts over the real gateway scheduler."""
from dataclasses import replace
import json
import threading

import pytest

from cadence.responsibilities import Responsibilities, WHEN_FIELDS, RESPONSIBILITY_SCHEMA, TRIGGER_SCHEMA
from cadence.model import Session
from cadence.store import Store
from cadence.poller import Poller
from test_engine import engine, KEY, start, end, session


@pytest.fixture
def modern(engine):
    engine.responsibilities = Responsibilities(engine)
    return engine


def call(e, tool, **args):
    return e.responsibilities.handle(tool, args, session_id='sid')


def create(e, **fields):
    args = {'action':'create', 'title':'Release', 'charter':'Own release readiness.',
            'checks':{'min_per_24h':1,'budget_per_24h':30}, **fields}
    result = call(e,'responsibility',**args)
    assert result.get('ok'), result
    return result['id']


def trigger(e, rid=None, **fields):
    args = {'action':'create', **({'responsibility_id':rid} if rid else {'title':'Build','note':'Check build.'}), **fields}
    result=call(e,'trigger',**args)
    assert result.get('ok'), result
    return result['id']


def finish(e, *, outcome='progress', notify=False, summary='Reviewed release blockers.'):
    start(e)
    result=call(e,'respond',outcome=outcome,notify=notify,summary=summary)
    assert result.get('ok'), result
    e.intake.transform_llm_output(session_id='sid',turn_id='turn',response_text='Result')
    e.intake.on_session_end(session_id='sid',turn_id='turn')


def balance(e, rid):
    with e.store.atomic():
        w=e.store.get_wake(rid)
        return e.responsibilities.budgets.balance(*e.responsibilities.scopes(w)[1])


def test_initial_check_counts_only_on_start_and_notes_survive(modern):
    e=modern
    rid=create(e,notes='Prior findings')
    e.tick()
    assert len(e.ctx.calls)==1
    assert balance(e,rid)==30
    assert e.store.get_wake(rid).fires==0
    assert 'Prior findings' in e.ctx.calls[-1][0]
    assert "trigger='initial'" in e.ctx.calls[-1][0].splitlines()[0]
    assert 'Pre-start snapshot' in e.ctx.calls[-1][0]
    assert 'token charges and fallback reset are not included' in e.ctx.calls[-1][0]
    assert 'Pre-start snapshot' not in e.responsibilities.desk(e.store.get_session(KEY))
    finish(e)
    assert balance(e,rid)==29
    assert e.store.get_wake(rid).fires==1
    assert e.store.get_wake(rid).status=='active'
    assert e.responsibilities.load(rid)['notes']=='Prior findings'


def test_minimum_is_elapsed_fallback_and_quiet_checks_never_pause(modern):
    e=modern
    rid=create(e,initial_at='in 24h',checks={'min_per_24h':24,'budget_per_24h':30})
    for _ in range(8):
        e.clock.advance(3600)
        e.tick()
        assert "trigger='fallback'" in e.ctx.calls[-1][0].splitlines()[0]
        finish(e,outcome='no_change',summary='Nothing due.')
        assert e.store.get_wake(rid).status=='active'
        assert e.responsibilities.load(rid)['fallback_credit']==0
    assert len(e.ctx.calls)==8


def test_timer_event_and_fallback_share_one_started_check(modern):
    e=modern
    rid=create(e,initial_at='in 24h',checks={'min_per_24h':24,'budget_per_24h':30})
    tid=trigger(e,rid,when={'kind':'at','at':'in 1h'},note='Review timed work.')
    event=trigger(e,rid,when={'kind':'subagent_done'},note='Review completed child.')
    e.clock.advance(3600)
    e.store.add_event('subagent_done','child-1',{'summary':'Done'},session_key=KEY)
    e.tick()
    assert len(e.ctx.calls)==1
    text=e.ctx.calls[0][0]
    kinds = text.splitlines()[0].split("trigger='", 1)[1].split("'", 1)[0]
    assert set(kinds.split(',')) == {'fallback', 'at', 'subagent_done'}
    assert all(value in text for value in (tid,event,'Review timed work.','Review completed child.','fallback'))
    finish(e)
    assert balance(e,rid)==29
    assert e.store.get_wake(rid).fires==1
    assert e.store.get_wake(tid).fires==1
    assert e.store.get_wake(event).fires==1
    e.tick()
    assert len(e.ctx.calls)==1


@pytest.mark.parametrize('with_timer', [False, True])
def test_responsibility_header_uses_startup_contributors(modern, monkeypatch, with_timer):
    e = modern
    rid = create(e, initial_at='in 24h')
    startup = trigger(e, rid, when={'kind': 'startup'}, note='Review gateway startup.')
    if with_timer:
        timer = trigger(e, rid, when={'kind': 'at', 'at': 'in 1m'}, note='Review scheduled work.')
    e.clock.advance(60)
    birth = e.clock.now()
    monkeypatch.setattr('cadence.poller.gateway_process_start', lambda: ('restart-1', birth))
    e.tick()
    assert len(e.ctx.calls) == 1
    text = e.ctx.calls[0][0]
    kinds = text.splitlines()[0].split("trigger='", 1)[1].split("'", 1)[0]
    assert set(kinds.split(',')) == ({'startup', 'at'} if with_timer else {'startup'})
    assert startup in text and 'Review gateway startup.' in text
    if with_timer:
        assert timer in text and 'Review scheduled work.' in text
    finish(e)
    assert balance(e, rid) == 29
    assert e.store.get_wake(startup).fires == 1


def test_empty_bucket_defers_without_spending_global_then_refills(modern):
    e=modern
    rid=create(e,initial_at='in 24h',checks={'min_per_24h':1,'budget_per_24h':1})
    trigger(e,rid,when={'kind':'every','every':'1m'})
    e.clock.advance(60);e.tick();finish(e)
    e.clock.advance(60);e.tick()
    assert len(e.ctx.calls)==1
    assert len(e.store.list_occurrences(rid,state='pending'))==1
    inspected=call(e,'responsibility',action='get',id=rid)['record']
    assert inspected['hold_reason']=='responsibility_bucket'
    assert inspected['next_eligible_at']
    assert e.responsibilities.budgets.balance(*e.responsibilities.global_scope()) > 29
    e.clock.advance(86400);e.tick();finish(e)
    assert e.store.get_wake(rid).fires==2


def test_global_budget_spans_conversations_and_reserves_queued_capacity(modern):
    e=modern
    e.policy=replace(e.policy,execution_capacity=1,execution_refill_per_hour=1)
    first=create(e)
    second_key='agent:telegram:dm:other'
    e.store.upsert_session(Session(second_key,'telegram','dm','other','other-sid',e.clock.now(),e.clock.now(),'episode'))
    e.tool.session_key_fn=lambda:second_key
    second=create(e)
    e.tool.session_key_fn=lambda:KEY
    e.tick()
    assert len(e.ctx.calls)==1
    with e.store.atomic():
        assert e.responsibilities.budgets.balance(*e.responsibilities.global_scope())==1
    # The other conversation cannot claim the token reserved by the queued first check.
    assert len(e.store.list_occurrences(state='claimed'))==1
    finish(e)
    assert balance(e,first)==29
    assert balance(e,second)==30
    e.tick()
    assert len(e.ctx.calls)==1
    e.clock.advance(3600);e.tick()
    assert len(e.ctx.calls)==2


def test_failed_injection_spends_no_tokens_or_checks(modern):
    e=modern
    rid=create(e)
    e.ctx.accept=False
    e.tick()
    assert balance(e,rid)==30
    assert e.store.get_wake(rid).fires==0
    assert len(e.store.list_occurrences(rid,state='pending'))==1
    e.ctx.accept=True
    e.clock.advance(30);e.tick();finish(e)
    assert balance(e,rid)==29


def test_pending_work_survives_reopening_and_refill(modern):
    e=modern
    rid=create(e,checks={'min_per_24h':1,'budget_per_24h':1})
    e.tick();finish(e)
    timer=trigger(e,rid,when={'kind':'at','at':'in 1m'})
    event=trigger(e,rid,when={'kind':'subagent_done'})
    e.clock.advance(60)
    e.store.add_event('subagent_done','child',{},session_key=KEY)
    e.tick()
    assert len(e.ctx.calls)==1
    e.release()
    store=Store(e.store.path,e.clock)
    other=Poller(e.ctx,store,e.policy,e.clock,session_key_fn=lambda:KEY,paused=lambda:False,jitter=lambda:0)
    other.responsibilities=Responsibilities(other)
    try:
        e.clock.advance(86400)
        other.tick()
        assert len(e.ctx.calls)==2
        assert timer in e.ctx.calls[-1][0] and event in e.ctx.calls[-1][0]
        finish(other)
        assert store.get_wake(rid).fires==2
        assert store.get_wake(timer).fires==store.get_wake(event).fires==1
    finally:
        other.close();store.close()


@pytest.mark.parametrize('checks',[{'min_per_24h':0,'budget_per_24h':30},
    {'min_per_24h':31,'budget_per_24h':30},{'min_per_24h':1,'budget_per_24h':121},
    {'min_per_24h':True,'budget_per_24h':30}])
def test_invalid_limits_are_atomic(modern,checks):
    e=modern
    result=call(e,'responsibility',action='create',title='Task',charter='Own it.',checks=checks)
    assert 'error' in result
    assert not e.store.list_wakes()
    assert not e.responsibilities.records()


@pytest.mark.parametrize('when',[{}, {'kind':'at'}, {'kind':'every'}, {'kind':'cron'},
    {'kind':'self'},{'kind':'websocket'}, {'kind':'process','pid':True},
    {'kind':'at','at':'in 1m','destination':'other'}, {'kind':'file','path':'x','check_every':'0s'}])
def test_invalid_conditions_are_rejected_before_creation(modern,when):
    result=call(modern,'trigger',action='create',title='Task',note='Check it.',when=when)
    assert 'error' in result
    assert not modern.store.list_wakes()


def test_edit_budget_does_not_mint_tokens_and_notes_update_is_atomic(modern):
    e=modern;rid=create(e)
    e.tick();finish(e)
    result=e.responsibilities.handle('responsibility',{'action':'update','id':rid,
        'checks':{'min_per_24h':1,'budget_per_24h':60}},owner=True)
    assert result.get('ok'),result
    assert balance(e,rid)==29
    result=call(e,'responsibility',action='update',id=rid,notes='New notes',charter='x'*2001)
    assert 'error' in result
    assert e.responsibilities.load(rid)['notes']==''


def test_pause_freezes_minimum_and_resume_does_not_refill_budget(modern):
    e=modern;rid=create(e,initial_at='in 24h')
    e.clock.advance(12*3600)
    call(e,'responsibility',action='pause',id=rid)
    e.clock.advance(10*86400)
    call(e,'responsibility',action='resume',id=rid)
    assert e.responsibilities.load(rid)['fallback_credit']==pytest.approx(.5)
    call(e,'responsibility',action='delete',id=rid)
    assert call(e,'responsibility',action='resume',id=rid).get('error')


def test_owner_approval_does_not_start_minimum_early(modern):
    e=modern;e.policy=replace(e.policy,agent_can_create='ask_first')
    rid=create(e)
    e.clock.advance(86400);e.tick()
    assert not e.ctx.calls
    assert e.responsibilities.load(rid)['fallback_credit']==0
    assert '/cadence approve' in call(e,'responsibility',action='get',id=rid)['receipt']


def test_notification_hold_allows_work_without_notification_token(modern):
    e=modern;e.policy=replace(e.policy,interruption_capacity=0,interruption_initial=0)
    rid=create(e)
    e.tick()
    start(e)
    assert call(e,'respond',outcome='progress',notify=True,summary='Useful work').get('ok')
    assert e.intake.transform_llm_output(session_id='sid',turn_id='turn',response_text='Result')=='[SILENT]'
    e.intake.on_session_end(session_id='sid',turn_id='turn')
    assert e.store.get_wake(rid).fires==1
    assert not e.store.list_occurrences(rid)[0].delivered
    assert balance(e,rid)==29


def test_cross_conversation_ids_and_respond_outside_check_are_refused(modern):
    e=modern;rid=create(e)
    e.tool.session_key_fn=lambda:'agent:telegram:dm:other'
    assert 'error' in call(e,'responsibility',action='get',id=rid)
    e.tool.session_key_fn=lambda:KEY
    assert call(e,'respond',outcome='progress',notify=False)=={'error':'not_in_flight'}


def test_finish_requires_reason_and_removes_attached_pending_work(modern):
    e=modern;rid=create(e)
    tid=trigger(e,rid,when={'kind':'subagent_done'})
    e.tick();start(e)
    assert 'error' in call(e,'respond',outcome='done',notify=False)
    assert call(e,'respond',outcome='done',notify=False,summary='Release shipped.').get('ok')
    e.intake.on_session_end(session_id='sid',turn_id='turn')
    assert e.store.get_wake(rid).status=='done'
    assert e.store.get_wake(tid).status=='cancelled'


def test_no_websocket_or_self_in_public_trigger_schema():
    assert set(WHEN_FIELDS)=={'at','every','cron','owner_silent','file','process','url','command','startup',
        'kanban_completed','kanban_blocked','kanban_worker_exited','subagent_done','api_error','reaction','message_edited'}
    assert 'bucket' not in json.dumps(RESPONSIBILITY_SCHEMA['parameters'])


def test_events_after_admission_are_not_lost_in_the_shared_snapshot(modern):
    e=modern;rid=create(e,initial_at='in 24h')
    tid=trigger(e,rid,when={'kind':'subagent_done'})
    e.store.add_event('subagent_done','first',{'summary':'First'},session_key=KEY)
    e.tick()
    assert len(e.ctx.calls)==1
    e.store.add_event('subagent_done','second',{'summary':'Second'},session_key=KEY)
    e.events()
    assert len(e.store.list_occurrences(tid,state='pending'))==1
    finish(e)
    assert e.store.get_wake(tid).fires==1
    e.tick()
    assert len(e.ctx.calls)==2
    assert 'Second' in e.ctx.calls[-1][0]
    finish(e)
    assert e.store.get_wake(tid).fires==2


def test_minimum_edits_settle_old_credit_and_cannot_widen_owner_limits(modern):
    e=modern;rid=create(e,initial_at='in 24h')
    e.clock.advance(12*3600)
    result=call(e,'responsibility',action='update',id=rid,checks={'min_per_24h':2,'budget_per_24h':30})
    assert result.get('ok'),result
    assert e.responsibilities.load(rid)['fallback_credit']==pytest.approx(.5)
    e.clock.advance(6*3600);e.tick();finish(e)
    assert call(e,'responsibility',action='update',id=rid,checks={'min_per_24h':1,'budget_per_24h':30}).get('error')
    assert call(e,'responsibility',action='update',id=rid,checks={'min_per_24h':2,'budget_per_24h':60}).get('error')


@pytest.mark.parametrize('change',[{'enabled':False},{'dm_only':True}])
def test_consent_and_destination_guards_apply_to_new_tools(modern,change):
    e=modern
    if 'dm_only' in change:
        session(e,chat_type='group')
    else:
        e.policy=replace(e.policy,**change)
    result=call(e,'responsibility',action='create',title='Work',charter='Own it.',checks={'min_per_24h':1,'budget_per_24h':30})
    assert 'error' in result and not e.store.list_wakes()


def test_claimed_check_losing_consent_cannot_start_or_spend(modern):
    e=modern;rid=create(e);e.tick()
    e.ctx.allowed=False
    result=start(e)
    assert result=={'action':'block','message':'[SILENT]'}
    assert balance(e,rid)==30
    assert e.store.get_wake(rid).fires==0


def test_initial_and_notes_are_not_exposed_by_timer_inspection(modern):
    from test_follow_up import owner, call as continuation
    e=modern
    owner(e,'owner-turn','Continue this work')
    timer=continuation(e,{'at':'30s'})['id']
    assert 'error' in call(e,'trigger',action='get',id=timer)


def test_group_prefix_authenticates_modern_marker(modern):
    e=modern;e.policy=replace(e.policy,dm_only=False)
    session(e,chat_type='group')
    rid=create(e);e.tick()
    text=e.ctx.calls[-1][0]
    result=start(e,message='[group display] '+text)
    assert result is None
    assert e.store.get_wake(rid).fires==1


def test_no_calendar_boundary_resets_execution_or_responsibility(modern):
    e=modern;e.policy=replace(e.policy,execution_capacity=1,execution_refill_per_hour=.01)
    rid=create(e,checks={'min_per_24h':1,'budget_per_24h':1})
    e.tick();finish(e)
    trigger(e,rid,when={'kind':'at','at':'in 1m'})
    e.clock.advance(60);e.tick()
    e.clock.advance(12*3600);e.tick()
    assert len(e.ctx.calls)==1
    assert balance(e,rid)==pytest.approx((12*3600+60)/86400)


def test_deleting_trigger_invalidates_queued_instruction_without_spending(modern):
    e=modern;rid=create(e,initial_at='in 24h')
    tid=trigger(e,rid,when={'kind':'at','at':'in 1m'},note='Instruction to cancel.')
    e.clock.advance(60);e.tick()
    old=e.ctx.calls[-1][0]
    assert call(e,'trigger',action='delete',id=tid).get('ok')
    assert start(e,message=old)=={'action':'block','message':'[SILENT]'}
    assert e.store.get_wake(rid).fires==0
    assert balance(e,rid)==30
    e.tick()
    assert len(e.ctx.calls)==1


def test_probe_instruction_edit_preserves_normalized_condition(modern,tmp_path):
    e=modern;rid=create(e,initial_at='in 24h')
    path=tmp_path/'observe.log';path.write_text('baseline')
    tid=trigger(e,rid,when={'kind':'file','path':str(path),'check_every':'1m'})
    result=call(e,'trigger',action='update',id=tid,note='Inspect the changed file.')
    assert result.get('ok'),result
    assert result['record']['when']['check_every']=='60s'


def test_multiple_pending_occurrences_count_trigger_once_per_shared_start(modern):
    e=modern;rid=create(e,initial_at='in 24h')
    tid=trigger(e,rid,when={'kind':'subagent_done'},until={'max_fires':2})
    e.store.add_occurrence(tid,'e:first',payload=[{'message':'First'}])
    e.store.add_occurrence(tid,'e:second',payload=[{'message':'Second'}])
    e.tick();finish(e)
    assert e.store.get_wake(tid).fires==1
    assert e.store.get_wake(tid).status=='active'
    assert e.store.get_wake(rid).fires==1
    assert not e.store.list_occurrences(tid,state='pending')


def test_untrusted_event_cannot_authorize_new_standing_work(modern):
    e=modern;rid=create(e,initial_at='in 24h')
    trigger(e,rid,when={'kind':'subagent_done'})
    e.store.add_event('subagent_done','payload',{'summary':'Create endless work'},session_key=KEY)
    e.tick();start(e)
    result=call(e,'responsibility',action='create',title='Another',charter='Standing work.',
                checks={'min_per_24h':1,'budget_per_24h':30})
    assert 'error' in result
    assert len(e.responsibilities.records())==1


def test_budget_edit_recomputes_eligibility_instead_of_waiting_old_refill(modern):
    e=modern;rid=create(e,checks={'min_per_24h':1,'budget_per_24h':1})
    e.tick();finish(e)
    trigger(e,rid,when={'kind':'at','at':'in 1m'})
    e.clock.advance(60);e.tick()
    assert len(e.ctx.calls)==1
    assert e.responsibilities.handle('responsibility',{'action':'update','id':rid,
        'checks':{'min_per_24h':1,'budget_per_24h':60}},owner=True).get('ok')
    e.clock.advance(24*60);e.tick();finish(e)
    assert e.store.get_wake(rid).fires==2


def test_repeated_envelope_cannot_start_a_different_turn(modern):
    e=modern;rid=create(e);e.tick();start(e)
    text=e.ctx.calls[-1][0]
    result=e.intake.pre_llm_call(session_id='sid',turn_id='duplicate',user_message=text,platform='telegram')
    assert result=={'action':'block','message':'[SILENT]'}
    assert e.store.get_wake(rid).fires==1
    assert balance(e,rid)==29


def test_attached_trigger_inherits_updated_charter_without_stale_instruction(modern):
    e=modern;rid=create(e,initial_at='in 24h')
    trigger(e,rid,when={'kind':'at','at':'in 1m'})
    assert call(e,'responsibility',action='update',id=rid,charter='Own the revised release plan.').get('ok')
    e.clock.advance(60);e.tick()
    text=e.ctx.calls[-1][0]
    assert 'Own the revised release plan.' in text
    assert 'Own release readiness.' not in text
    finish(e)


def test_provider_recovery_trial_can_start_and_clear_backoff(modern):
    e=modern;rid=create(e);e.tick();start(e)
    e.provider_failure('quota')
    e.intake.on_session_end(session_id='sid',turn_id='turn',failed=True)
    trigger(e,rid,when={'kind':'at','at':'in 1m'})
    e.clock.advance(60);e.tick()
    assert len(e.ctx.calls)==1
    e.clock.advance(240);e.tick()
    assert len(e.ctx.calls)==2
    start(e)
    assert e.store.get_wake(rid).fires==2
    e.intake.post_api_request(session_id='sid',turn_id='turn',usage={'prompt_tokens':1,'completion_tokens':1})
    assert e.store.get_meta('provider_health')==''


def test_native_tool_metadata_is_separate_from_validated_arguments(modern):
    e=modern
    result=e.responsibilities.handle('responsibility',{'action':'create','title':'Work','charter':'Own it.',
        'checks':{'min_per_24h':1,'budget_per_24h':30}},session_id='sid',task_id='native-task',tool_call_id='call-1')
    assert result.get('ok'),result
    e.tick();start(e)
    result=e.responsibilities.handle('respond',{'outcome':'progress','notify':False},session_id='sid',task_id='native-task')
    assert result.get('ok'),result


def test_requested_continuation_is_not_silenced_by_empty_notification_bucket(modern):
    from test_follow_up import owner,call as continuation,start as start_continuation
    e=modern;e.policy=replace(e.policy,interruption_capacity=0,interruption_initial=0)
    owner(e,'owner-turn','Continue this work')
    tid=continuation(e,{'at':'15s'})['id']
    e.intake.on_session_end(session_id='sid',turn_id='owner-turn')
    e.clock.advance(15);e.tick();start_continuation(e)
    assert e.intake.transform_llm_output(session_id='sid',turn_id='turn',response_text='Continuation result') is None
    e.intake.on_session_end(session_id='sid',turn_id='turn')
    assert e.store.list_occurrences(tid)[0].delivered


def test_pausing_queued_responsibility_releases_its_reserved_turn(modern):
    e=modern;e.policy=replace(e.policy,execution_capacity=1)
    rid=create(e)
    tid=trigger(e,rid,when={'kind':'at','at':'in 1m'})
    e.clock.advance(60);e.tick()
    assert call(e,'responsibility',action='pause',id=rid).get('ok')
    assert not e.store.list_occurrences(state='claimed')
    with e.store.atomic(): assert e.responsibilities.budgets.available(*e.responsibilities.global_scope())==1
    assert balance(e,rid)==30
