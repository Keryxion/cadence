"""Ambiguous delivery never starts a second external action."""
from types import SimpleNamespace as NS

from test_requests import pair, setup_names, ask, inbound, CURRENT


def test_answer_lost_after_target_acted_is_durable(pair):
    e, r = pair
    setup_names(e, r)
    rid = ask(e,r)['request']
    inbound(e,r,'kitchen',internal=True,text=e.ctx.calls[-1][0])
    e.ctx.accept=False
    assert r.handle({'action':'answer','id':rid,'outcome':'accepted','summary':'Timer set','notify':False},session_id='kitchen-sid')['ok']
    assert r._row(rid)['outcome']=='accepted'
    assert r._row(rid)['answer_state']=='unknown'
    assert len(e.ctx.calls)==2
    r.expire()
    assert len(e.ctx.calls)==2
    CURRENT.key='mac'
    rows=r.handle({'action':'list'},session_id='mac-sid')['requests']
    assert rows[0]['outcome']=='accepted' and rows[0]['answer_state']=='unknown'


def test_host_exception_is_unknown_and_no_retry(pair):
    e,r=pair
    setup_names(e,r)
    def broken(*args,**kw): raise RuntimeError('lost acceptance')
    e.ctx.inject_message=broken
    result=ask(e,r)
    assert result['error']=='unknown'
    assert r._row(result['request'])['outcome']=='unknown'
    assert ask(e,r)['error']=='duplicate'






def test_no_effect_after_answer_or_deadline(pair):
    e,r=pair
    setup_names(e,r)
    rid=ask(e,r)['request']
    inbound(e,r,'kitchen',internal=True,text=e.ctx.calls[-1][0])
    e.clock.advance(61)
    result=r.hook('pre_tool_call',session_id='kitchen-sid',turn_id='turn-kitchen',tool_name='countdown',args={})
    assert result is None  # Normal tools remain available; timeout prevents late acceptance.
    assert r.handle({'action':'answer','id':rid,'outcome':'accepted','summary':'Set','notify':False},session_id='kitchen-sid')['error']=='already_ended'
