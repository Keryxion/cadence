"""Immediate requests: durable protocol, trusted admission, no external effects."""
import json
from types import SimpleNamespace as NS

import pytest

from cadence.model import Session
from cadence.poller import Poller
from cadence.policy import Policy
from cadence.store import Store
from test_engine import GatewayCtx

CURRENT = NS(key='mac')


@pytest.fixture
def pair(tmp_path, clock, monkeypatch):
    monkeypatch.setattr('cadence.requests.session_env',
        lambda name: getattr(CURRENT, 'actor', '') if name == 'HERMES_SESSION_ACTOR_ID' else '')
    from cadence.requests import Requests
    ctx = GatewayCtx(tmp_path)
    e = Poller(ctx, Store(tmp_path/'pulse.db', clock), Policy(clock=clock, quiet_hours='', timezone='UTC'),
               clock, paused=lambda: False, session_key_fn=lambda: CURRENT.key)
    CURRENT.key = 'mac'
    for key in ('mac', 'kitchen'):
        e.store.upsert_session(Session(key, 'telegram', 'dm', key, key+'-sid'))
    r = Requests(e)
    e.requests = r
    r.host_supported = True
    yield e, r
    e.close()
    e.store.close()


def inbound(e, r, key='mac', actor='user-mac', internal=False, text='Set a kitchen timer'):
    CURRENT.key = key
    CURRENT.actor = '' if internal else actor
    event = NS(internal=internal, text=text, message_id='m1',
               source=NS(user_id=actor, is_bot=False, platform=NS(value='telegram'), chat_type='dm', chat_id=key),
               metadata={'hermes_plugin_id': 'cadence', 'hermes_plugin_injection': True} if internal else {})
    gateway = NS(_session_key_for_source=lambda source: key, _is_user_authorized_for_source=lambda source: True)
    r.hook('pre_gateway_dispatch', event=event, gateway=gateway)
    return r.hook('pre_llm_call', session_id=key+'-sid', turn_id='turn-'+key, user_message=text)


def setup_names(e, r):
    for key, name in [('mac', 'MacBook'), ('kitchen', 'Kitchen')]:
        CURRENT.key = key
        assert r.handle({'action': 'rename', 'name': name}, session_id=key+'-sid')['ok']
    inbound(e, r)


def ask(e, r, **extra):
    return r.handle({'action': 'ask', 'to': 'Kitchen', 'note': 'Set a 5 minute timer', **extra}, session_id='mac-sid')


def test_roundtrip_silent_target_and_source_confirmation(pair):
    e, r = pair
    setup_names(e, r)
    result = ask(e, r)
    assert result['ok']
    rid = result['request']
    text, key = e.ctx.calls[-1]
    assert key == 'kitchen'
    assert 'YOUR OWN tools' in inbound(e, r, key, internal=True, text=text)['context']
    assert r.standing('kitchen-sid') is False  # A message is not an owner_asked grant.
    assert r.hook('transform_llm_output', session_id='kitchen-sid', turn_id='turn-kitchen', response_text='Done') == '[SILENT]'
    answer = {'action': 'answer', 'id': rid, 'outcome': 'accepted', 'summary': 'Kitchen timer set for five minutes.', 'notify': False}
    assert r.handle(answer, session_id='kitchen-sid')['ok']
    assert e.ctx.calls[-1][1] == 'mac'
    assert len(e.ctx.calls) == 2
    assert r.handle(answer, session_id='kitchen-sid')['ok']
    assert len(e.ctx.calls) == 2
    CURRENT.key = 'mac'
    assert r.handle({'action': 'list'}, session_id='mac-sid')['requests'][0]['outcome'] == 'accepted'






def test_unknown_outcome_never_retries(pair):
    e, r = pair
    setup_names(e, r)
    result = ask(e, r)
    e.clock.advance(61)
    r.expire()
    CURRENT.key = 'mac'
    rows = r.handle({'action': 'list'}, session_id='mac-sid')['requests']
    assert rows[0]['outcome'] == 'unknown'
    assert len(e.ctx.calls) == 2  # one request, one uncertainty notice
    r.expire()
    assert len(e.ctx.calls) == 2
    inbound(e, r)
    assert ask(e, r)['error'] == 'duplicate'
    assert result['request'] == rows[0]['id']


def test_duplicate_injection_and_forged_answer_are_blocked(pair):
    e, r = pair
    setup_names(e, r)
    result = ask(e, r)
    text = e.ctx.calls[-1][0]
    # A human quoting the envelope cannot become a request turn.
    blocked = inbound(e, r, 'kitchen', internal=False, text=text)
    assert blocked['action'] == 'block'
    assert r.handle({'action': 'answer', 'id': result['request'], 'outcome': 'accepted', 'summary': 'Fake', 'notify': False}, session_id='kitchen-sid')['error'] == 'not_in_request'
    inbound(e, r, 'kitchen', internal=True, text=text)
    assert inbound(e, r, 'kitchen', internal=True, text=text)['action'] == 'block'


def test_rename_casefold_and_stable_record(pair):
    e, r = pair
    setup_names(e, r)
    result = ask(e, r)
    CURRENT.key = 'kitchen'
    assert r.handle({'action': 'rename', 'name': 'MACBOOK'}, session_id='kitchen-sid')['error'] == 'name_taken'
    assert r.handle({'action': 'rename', 'name': 'Cooking'}, session_id='kitchen-sid')['ok']
    inbound(e, r, 'kitchen', internal=True, text=e.ctx.calls[-1][0])
    assert r.handle({'action': 'answer', 'id': result['request'], 'outcome': 'accepted', 'summary': 'Set', 'notify': False}, session_id='kitchen-sid')['ok']


def test_platform_filter_and_host_support_fail_closed(pair):
    e, r = pair
    setup_names(e, r)
    r.host_supported = False
    assert ask(e, r)['error'] == 'unsupported_host'
    assert not e.ctx.calls


def test_reopen_suppresses_duplicate_and_keeps_unknown(pair):
    from cadence.requests import Requests
    e, r = pair
    setup_names(e, r)
    ask(e, r)
    reopened = Requests(e)
    reopened.host_supported = True
    inbound(e, reopened)
    assert ask(e, reopened)['error'] == 'duplicate'


def test_no_nested_ask_or_cross_request_answer(pair):
    e, r = pair
    setup_names(e, r)
    ask(e, r)
    inbound(e, r, 'kitchen', internal=True, text=e.ctx.calls[-1][0])
    assert r.handle({'action': 'ask', 'to': 'MacBook', 'note': 'Relay'}, session_id='kitchen-sid')['error'] == 'nested_request'
    assert r.handle({'action': 'answer', 'id': 'other', 'outcome': 'accepted', 'summary': 'Fake', 'notify': False}, session_id='kitchen-sid')['error'] == 'not_in_request'
