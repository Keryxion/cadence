"""Conversation requests share profile execution and notification capacity."""
from dataclasses import replace
import pytest

from cadence.responsibilities import Responsibilities
from test_requests import pair, setup_names, ask, inbound, CURRENT


def test_request_and_answer_charge_once_on_actual_start(pair):
    e,r=pair
    e.responsibilities=Responsibilities(e)
    m=e.responsibilities
    setup_names(e,r)
    rid=ask(e,r)['request']
    with e.store.atomic(): assert m.budgets.balance(*m.global_scope())==30
    text=e.ctx.calls[-1][0]
    assert 'context' in inbound(e,r,'kitchen',internal=True,text=text)
    with e.store.atomic(): assert m.budgets.balance(*m.global_scope())==29
    assert inbound(e,r,'kitchen',internal=True,text=text)['action']=='block'
    with e.store.atomic(): assert m.budgets.balance(*m.global_scope())==29
    assert r.handle({'action':'answer','id':rid,'outcome':'accepted','summary':'Accepted.','notify':False},session_id='kitchen-sid')['ok']
    assert 'context' in inbound(e,r,'mac',internal=True,text=e.ctx.calls[-1][0])
    with e.store.atomic(): assert m.budgets.balance(*m.global_scope())==28
    assert r.hook('transform_llm_output',session_id='mac-sid',turn_id='turn-mac',response_text='Accepted') is None
    r.hook('on_session_end',session_id='mac-sid',turn_id='turn-mac',completed=True)
    with e.store.atomic(): assert m.notification_balance()==14


def test_answer_waits_for_execution_refill_without_resending_request(pair):
    e,r=pair
    e.policy=replace(e.policy,execution_capacity=1,execution_refill_per_hour=60)
    e.responsibilities=Responsibilities(e)
    setup_names(e,r)
    rid=ask(e,r)['request']
    inbound(e,r,'kitchen',internal=True,text=e.ctx.calls[-1][0])
    assert r.handle({'action':'answer','id':rid,'outcome':'accepted','summary':'Accepted.','notify':False},session_id='kitchen-sid')['ok']
    assert len(e.ctx.calls)==1
    e.clock.advance(60);r.expire()
    assert len(e.ctx.calls)==2
    assert 'context' in inbound(e,r,'mac',internal=True,text=e.ctx.calls[-1][0])
    with e.store.atomic(): assert e.responsibilities.budgets.balance(*e.responsibilities.global_scope())==0
    r.expire()
    assert len(e.ctx.calls)==2


def test_request_turn_usage_is_included_in_agent_spend(pair,monkeypatch):
    e,r=pair
    e.responsibilities=Responsibilities(e)
    setup_names(e,r);ask(e,r)
    inbound(e,r,'kitchen',internal=True,text=e.ctx.calls[-1][0])
    monkeypatch.setattr('cadence.cache.cost',lambda *a,**kw:.01)
    r.hook('post_api_request',session_id='kitchen-sid',turn_id='turn-kitchen',usage={'prompt_tokens':10})
    assert e.store.agent_cost_today('kitchen',e.policy.resolved_timezone())['cost_microusd']==10000
