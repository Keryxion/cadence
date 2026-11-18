"""Request turns carry bounded standing, never model-asserted authority."""
from test_requests import pair, setup_names, ask, inbound, CURRENT


def target(e, r):
    setup_names(e, r)
    ask(e, r)
    inbound(e, r, 'kitchen', internal=True, text=e.ctx.calls[-1][0])








def test_normal_turn_end_removes_owner_standing(pair):
    e, r = pair
    setup_names(e, r)
    r.hook('on_session_end', session_id='mac-sid', turn_id='turn-mac')
    assert ask(e,r)['error'] == 'missing_turn'
