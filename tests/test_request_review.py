"""Regressions for the independent request review (no gateway/device claim)."""
import json
from types import SimpleNamespace as NS

import pytest

from test_requests import pair, setup_names, ask, inbound, CURRENT








def test_same_note_new_authenticated_turn_after_success(pair):
    e, r = pair
    setup_names(e, r)
    first = ask(e, r)['request']
    inbound(e, r, 'kitchen', internal=True, text=e.ctx.calls[-1][0])
    assert r.handle({'action':'answer','id':first,'outcome':'accepted','summary':'set','notify':False}, session_id='kitchen-sid')['ok']
    inbound(e, r)
    # A new host-authenticated turn, not a durable replay of turn-mac.
    r.hook('pre_gateway_dispatch', event=NS(internal=False, text='Again', source=NS(user_id='user-mac', is_bot=False)),
           gateway=NS(_session_key_for_source=lambda s:'mac', _is_user_authorized_for_source=lambda s:True))
    r.hook('pre_llm_call', session_id='mac-sid', turn_id='next-human', user_message='Again')
    second = ask(e, r)
    assert second['ok'] and second['request'] != first
    assert ask(e, r)['error'] == 'duplicate'




def test_same_note_new_human_turn_after_unknown_does_not_replay_old_request(pair):
    e, r = pair
    setup_names(e, r)
    first = ask(e, r)['request']
    e.clock.advance(61)
    r.expire()
    inbound(e, r)
    assert ask(e, r)['error'] == 'duplicate'  # Same originating turn, even after timeout.
    r.hook('pre_gateway_dispatch', event=NS(internal=False, text='New timer',
           source=NS(user_id='user-mac', is_bot=False)),
           gateway=NS(_session_key_for_source=lambda s:'mac', _is_user_authorized_for_source=lambda s:True))
    r.hook('pre_llm_call', session_id='mac-sid', turn_id='new-human', user_message='New timer')
    second = ask(e, r)
    assert second['ok'] and second['request'] != first
    assert r._row(first)['outcome'] == 'unknown'
    assert r._row(second['request'])['origin_turn'] == 'new-human'


def test_missing_origin_turn_cannot_authorize_ask(pair):
    e, r = pair
    setup_names(e, r)
    r.hook('pre_gateway_dispatch', event=NS(internal=False, text='Timer',
           source=NS(user_id='user-mac', is_bot=False)),
           gateway=NS(_session_key_for_source=lambda s:'mac', _is_user_authorized_for_source=lambda s:True))
    r.hook('pre_llm_call', session_id='mac-sid', user_message='Timer')
    assert ask(e, r)['error'] == 'missing_turn'
    assert not e.ctx.calls


def test_old_host_fails_closed_before_record_or_injection(pair, monkeypatch):
    from cadence.requests import Requests
    e, r = pair
    setup_names(e, r)
    monkeypatch.setattr(Requests, "_host_supported", staticmethod(lambda: False))
    old_host = Requests(e)
    assert not old_host.host_supported
    result = ask(e, old_host)
    assert result['error'] == 'unsupported_host'
    assert 'provenance' in result['detail']
    assert e.store.connection.execute('SELECT COUNT(*) FROM session_requests').fetchone()[0] == 0
    assert not e.ctx.calls
    assert old_host.hook('transform_llm_output', session_id='mac-sid', response_text='Normal') is None
    assert old_host.hook('pre_tool_call', session_id='mac-sid', tool_name='countdown') is None


def test_registration_never_holds_every_profile_reply():
    from cadence.registration import _register_surfaces
    class Context:
        def __init__(self): self.holds = []
        def register_tool(self, **kw): pass
        def register_command(self, **kw): pass
        def register_hook(self, name, callback, *, hold_stream=False): self.holds.append(hold_stream)
    ctx = Context()
    runtime = NS()
    _register_surfaces(ctx, runtime)
    assert not any(ctx.holds)


