"""Named opt-in communication keeps ordinary tools and streaming."""
from contextvars import ContextVar
from types import SimpleNamespace as NS

from test_requests import pair, setup_names, ask, inbound, CURRENT


def test_unnamed_directory_is_visible_but_not_addressable(pair):
    e, r = pair
    e.store.set_meta('request_title:kitchen', 'Kitchen display')
    result = r.handle({'action': 'names'}, session_id='mac-sid')
    assert result.get('ok'), result
    entry = next(x for x in result['names'] if x['title'] == 'Kitchen display')
    assert entry['name'] is None and entry['addressable'] is False
    assert r.handle({'action':'rename','name':'MacBook'}, session_id='mac-sid')['ok']
    inbound(e, r)
    for destination in ('Kitchen display', 'kitchen', 'kitchen-sid'):
        assert ask(e, r, to=destination)['error'] == 'unknown'
    assert not e.ctx.calls
    assert e.store.connection.execute('SELECT COUNT(*) FROM request_names').fetchone()[0] == 1


def test_self_naming_without_owner_mapping_allows_general_request(pair):
    e, r = pair
    e.ctx.settings.clear()
    setup_names(e, r)
    result = ask(e, r, note='Inspect the project and discuss anything relevant.')
    assert result.get('ok'), result
    context = inbound(e, r, 'kitchen', internal=True, text=e.ctx.calls[-1][0])['context']
    assert 'Do not speak' not in context and 'interim' in context
    for tool in ('terminal', 'web_search', 'speak_this', 'tool_call', 'countdown', 'pulse'):
        assert r.hook('pre_tool_call', session_id='kitchen-sid',
                      turn_id='turn-kitchen', tool_name=tool) is None
    assert r.hook('transform_llm_output', session_id='ordinary-sid', response_text='Normal') is None


def test_group_source_and_target_are_not_artificially_blocked(pair):
    e, r = pair
    setup_names(e, r)
    for key in ('mac', 'kitchen'):
        e.store.cas_session(key, {'chat_type':'dm'}, chat_type='group')
    assert ask(e, r)['ok']


def test_real_host_provenance_capability_not_silence(pair, monkeypatch):
    from cadence.requests import Requests
    import sys
    import gateway
    e, _ = pair
    def set_session_vars(*, turn_event=None): pass
    host = NS(set_session_vars=set_session_vars, _SESSION_TURN_EVENT=ContextVar('event', default=None))
    monkeypatch.setitem(sys.modules, 'gateway.session_context', host)
    monkeypatch.setattr(gateway, 'session_context', host)
    r = Requests(e)
    setup_names(e, r)
    assert ask(e, r)['ok']


def test_absent_provenance_fails_closed_before_request_write(pair, monkeypatch):
    from cadence.requests import Requests
    import sys
    import gateway
    e, _ = pair
    host = NS(set_session_vars=lambda:None)
    monkeypatch.setitem(sys.modules, 'gateway.session_context', host)
    monkeypatch.setattr(gateway, 'session_context', host)
    r = Requests(e)
    setup_names(e, r)
    result = ask(e, r)
    assert result['error'] == 'unsupported_host'
    assert 'provenance' in result['detail']
    assert not e.ctx.calls
    assert e.store.connection.execute('SELECT COUNT(*) FROM session_requests').fetchone()[0] == 0
