"""Every ask result is one unmistakable state; names outlive sessions and restarts.

These assert the state, flags and whether a request record exists, never wording.
"""
import sys
from types import ModuleType, SimpleNamespace as NS

import pytest

from cadence import admission
from cadence.poller import Poller
from cadence.policy import Policy
from cadence.requests import Requests
from cadence.store import Store
from test_engine import GatewayCtx
from test_requests import pair, setup_names, ask, inbound, CURRENT


def records(r):
    return r.store.connection.execute('SELECT COUNT(*) FROM session_requests').fetchone()[0]


def host_says(monkeypatch, verdicts):
    """Stand in for the host's own admission check, per target conversation."""
    monkeypatch.setattr(admission, 'check', lambda manager, key: verdicts.get(key))


def listed(r, name):
    CURRENT.key = 'mac'
    return next(x for x in r.handle({'action': 'names'}, session_id='mac-sid')['names'] if x['name'] == name)


def deliver(e, r, sid='kitchen-sid'):
    """The host runs the injected envelope as a turn in the target conversation."""
    text, key = e.ctx.calls[-1]
    assert key == 'kitchen'
    CURRENT.key = 'kitchen'
    return r.hook('pre_llm_call', session_id=sid, turn_id='turn-'+sid, user_message=text)


def test_sent_request_is_awaiting_answer(pair):
    e, r = pair
    setup_names(e, r)
    result = ask(e, r)
    assert result['ok'] is True and result['state'] == 'awaiting_answer'
    assert 'error' not in result and records(r) == 1


def test_host_refusal_is_not_delivered_and_leaves_no_request(pair):
    e, r = pair
    setup_names(e, r)
    e.ctx.accept = False  # the host returned False: nothing was scheduled
    result = ask(e, r)
    assert 'ok' not in result
    assert result['error'] == 'not_delivered' and result['state'] == 'not_delivered'
    assert result['retry_safe'] is True and result['reason'] == 'host_refused'
    assert records(r) == 0
    e.ctx.accept = True
    again = ask(e, r)  # same turn, same note: a refused ask is not a duplicate
    assert again['ok'] is True and again['state'] == 'awaiting_answer'


def test_host_exception_is_unknown_and_keeps_the_request(pair):
    e, r = pair
    setup_names(e, r)
    def broken(*args, **kw): raise RuntimeError('lost acceptance')
    e.ctx.inject_message = broken
    result = ask(e, r)
    assert 'ok' not in result
    assert result['error'] == 'unknown' and result['state'] == 'unknown' and result['retry_safe'] is False
    assert r._row(result['request'])['outcome'] == 'unknown'


def test_the_three_ask_states_cannot_be_mistaken_for_each_other(pair, monkeypatch):
    e, r = pair
    setup_names(e, r)
    sent = ask(e, r)
    host_says(monkeypatch, {'kitchen': admission.NOT_READY})
    refused = ask(e, r, note='another')
    assert {sent['state'], refused['state']} == {'awaiting_answer', 'not_delivered'}
    assert sent.get('ok') is True and 'ok' not in refused and 'error' not in sent


def test_unknown_name_is_not_the_unknown_outcome(pair):
    e, r = pair
    setup_names(e, r)
    result = ask(e, r, to='Nobody')
    assert result['error'] == 'unknown_name' and 'state' not in result
    assert records(r) == 0 and not e.ctx.calls


def test_target_the_host_would_refuse_fails_at_once_without_sending(pair, monkeypatch):
    """Issue #9: the target had been started new and nobody had spoken to it since."""
    e, r = pair
    setup_names(e, r)
    host_says(monkeypatch, {'kitchen': admission.NOT_READY})
    assert listed(r, 'Kitchen')['reachable'] is False
    result = ask(e, r)
    assert result['state'] == 'not_delivered' and result['reason'] == 'target_not_ready'
    assert result['retry_safe'] is True and 'ok' not in result
    assert records(r) == 0 and not e.ctx.calls
    # Someone speaks to the target; the same ask, in the same turn, now goes through.
    host_says(monkeypatch, {})
    assert listed(r, 'Kitchen')['reachable'] is True
    assert ask(e, r)['state'] == 'awaiting_answer' and len(e.ctx.calls) == 1


def test_reachable_is_omitted_when_the_host_cannot_be_asked(pair):
    e, r = pair
    setup_names(e, r)  # the unit host exposes no session index or authority
    entry = listed(r, 'Kitchen')
    assert entry['addressable'] is True and 'reachable' not in entry


def test_request_that_never_reached_the_target_times_out_as_not_delivered(pair):
    e, r = pair
    setup_names(e, r)
    first = ask(e, r)
    e.clock.advance(61)
    r.expire()
    assert r._row(first['request'])['outcome'] == 'not_delivered'
    # Late arrival of the envelope cannot start the work after all.
    assert e.ctx.calls[-1][1] == 'mac'  # the asker is told once
    CURRENT.key = 'kitchen'
    late = r.hook('pre_llm_call', session_id='kitchen-sid', turn_id='late', user_message=e.ctx.calls[0][0])
    assert late['action'] == 'block' and r._row(first['request'])['request_sid'] is None
    inbound(e, r)
    again = ask(e, r)
    assert again['ok'] is True and again['request'] != first['request']


def test_request_the_target_received_but_never_answered_times_out_as_unknown(pair):
    e, r = pair
    setup_names(e, r)
    rid = ask(e, r)['request']
    assert 'context' in deliver(e, r)
    e.clock.advance(61)
    r.expire()
    assert r._row(rid)['outcome'] == 'unknown'


def test_name_then_new_session_on_target_then_ask_is_delivered(pair):
    """A name belongs to the conversation, not to the session id it had when chosen."""
    e, r = pair
    setup_names(e, r)
    # /new on the target: same conversation key, a session id Cadence has never seen.
    assert listed(r, 'Kitchen')['addressable'] is True
    result = ask(e, r)
    assert result['state'] == 'awaiting_answer'
    assert e.ctx.calls[-1][1] == 'kitchen'  # routed by conversation, not by a stored session id
    assert 'context' in deliver(e, r, 'kitchen-after-new')
    row = r._row(result['request'])
    assert row['state'] == 'started' and row['request_sid'] == 'kitchen-after-new'
    answer = r.handle({'action': 'answer', 'id': result['request'], 'outcome': 'accepted',
                       'summary': 'done', 'notify': False}, session_id='kitchen-after-new')
    assert answer['ok'] is True and r._row(result['request'])['outcome'] == 'accepted'


def test_name_then_gateway_restart_then_ask_is_delivered(pair, tmp_path, clock):
    e, r = pair
    setup_names(e, r)
    # Restart: a new process, host and plugin runtime over the same database.
    e.store.close()
    ctx = GatewayCtx(tmp_path)
    e2 = Poller(ctx, Store(tmp_path/'pulse.db', clock), Policy(clock=clock, quiet_hours='', timezone='UTC'),
                clock, paused=lambda: False, session_key_fn=lambda: CURRENT.key)
    r2 = Requests(e2)
    e2.requests = r2
    try:
        entry = listed(r2, 'Kitchen')
        assert entry['addressable'] is True and entry.get('reachable', True) is True
        inbound(e2, r2)  # only the asker speaks; nobody talks to the target or renames it
        result = ask(e2, r2)
        assert result['ok'] is True and result['state'] == 'awaiting_answer'
        assert 'context' in deliver(e2, r2)
        assert r2._row(result['request'])['state'] == 'started'
    finally:
        e2.close()
        e2.store.close()


@pytest.mark.parametrize('name', ['Sakura: Darrell’s iPhone', "Sakura: Darrell's iPhone", 'Arya: Echo Dot 2 6c47c3',
                                  'Sakura: ' + 'x'*32])
def test_title_style_names_store_list_match_and_route(pair, name):
    e, r = pair
    setup_names(e, r)
    CURRENT.key = 'kitchen'
    assert r.handle({'action': 'rename', 'name': name}, session_id='kitchen-sid') == {'ok': True, 'name': name}
    assert listed(r, name)['addressable'] is True
    inbound(e, r)
    for spelling in (name, name.upper(), '  ' + name.lower() + ' '):
        result = ask(e, r, to=spelling, note='note for ' + spelling)
        assert result.get('state') == 'awaiting_answer', result
        assert e.ctx.calls[-1][1] == 'kitchen'
        r.store.connection.execute('DELETE FROM session_requests')
    # The source may carry such a name too: the answer routes back to it.
    CURRENT.key = 'mac'
    assert r.handle({'action': 'rename', 'name': 'Sakura: MacBook Pro'}, session_id='mac-sid')['ok']
    rid = ask(e, r, to=name)['request']
    deliver(e, r)
    assert r.handle({'action': 'answer', 'id': rid, 'outcome': 'accepted', 'summary': 'ok', 'notify': False},
                    session_id='kitchen-sid')['ok']
    assert e.ctx.calls[-1][1] == 'mac'


def test_name_rules_the_converse_side_must_meet(pair):
    e, r = pair
    setup_names(e, r)
    CURRENT.key = 'kitchen'
    rename = lambda name: r.handle({'action': 'rename', 'name': name}, session_id='kitchen-sid')
    assert rename('x'*41)['error'] == 'invalid_name'  # 40 characters at most
    assert rename('x'*40)['ok']
    assert rename('MACBOOK')['error'] == 'name_taken'  # unique regardless of case
    assert rename('Sakura:\tiPhone')['error'] == 'invalid_name'  # no control characters
    # Straight and typographic apostrophes are different characters, so different names.
    assert rename('Darrell’s iPhone')['ok']
    inbound(e, r)
    assert ask(e, r, to="Darrell's iPhone")['error'] == 'unknown_name'


# The host probe itself, against stand-ins for the two Hermes modules it reads.

def probe(monkeypatch, *, entry, envelope, authority=object()):
    authorities, automation = ModuleType('gateway.session_authorities'), ModuleType('gateway.session_automation')
    authorities.authority_for_home = lambda host, home: authority
    automation.committed_route_envelope = lambda authority, entry: envelope
    monkeypatch.setitem(sys.modules, 'gateway', ModuleType('gateway'))
    monkeypatch.setitem(sys.modules, 'gateway.session_authorities', authorities)
    monkeypatch.setitem(sys.modules, 'gateway.session_automation', automation)
    host = NS(session_store=NS(lookup_by_session_key=lambda key: entry))
    return admission.check(NS(_gateway_message_injector=(host, None), home_path='home'), 'kitchen')


def test_probe_admits_a_conversation_holding_a_human_message(monkeypatch):
    assert probe(monkeypatch, entry=NS(origin=object(), suspended=False), envelope={'provenance': {}}) is None


@pytest.mark.parametrize('entry', [None, NS(origin=None, suspended=False), NS(origin=object(), suspended=True)])
def test_probe_refuses_a_conversation_the_host_cannot_route(monkeypatch, entry):
    assert probe(monkeypatch, entry=entry, envelope={'provenance': {}}) == admission.NOT_READY


def test_probe_refuses_a_fresh_session_nobody_has_spoken_to(monkeypatch):
    assert probe(monkeypatch, entry=NS(origin=object(), suspended=False), envelope=None) == admission.NOT_READY


def test_probe_does_not_guess(monkeypatch):
    entry = NS(origin=object(), suspended=False)
    assert probe(monkeypatch, entry=entry, envelope=None, authority=None) == admission.UNCHECKED
    assert admission.check(NS(_gateway_message_injector=(NS(), None), home_path='home'), 'kitchen') == admission.UNCHECKED
    def explode(key): raise RuntimeError('host changed shape')
    host = NS(session_store=NS(lookup_by_session_key=explode))
    assert admission.check(NS(_gateway_message_injector=(host, None), home_path='home'), 'kitchen') == admission.UNCHECKED
