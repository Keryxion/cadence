"""Would the host admit a plugin turn into this conversation right now?

`inject_message` answers before the gateway decides: True only means the turn was
scheduled, and a later refusal by the session authority is logged, never returned.
The authority admits a plugin turn only into a conversation whose current session
already holds a human message (a plugin may continue a chat, not open one), so a
conversation that was just started new or reset is refused until someone speaks to
it. This asks the host the same question it will ask itself, before anything is sent.

It reads host internals, so every miss degrades to UNCHECKED rather than a guess.
"""
UNCHECKED = 'unchecked'
NOT_READY = 'target_not_ready'


def check(manager, session_key):
    """None: the host would admit it. NOT_READY: it would refuse. UNCHECKED: cannot tell."""
    try:
        injector = getattr(manager, '_gateway_message_injector', None)
        host = injector[0] if injector else None
        lookup = getattr(getattr(host, 'session_store', None), 'lookup_by_session_key', None)
        if not callable(lookup): return UNCHECKED
        try:
            from gateway.session_authorities import authority_for_home
            from gateway.session_automation import committed_route_envelope
        except ImportError:
            return UNCHECKED  # A host without a session authority routes through the adapter.
        entry = lookup(session_key)
        if entry is None or getattr(entry, 'origin', None) is None or getattr(entry, 'suspended', False):
            return NOT_READY
        authority = authority_for_home(host, manager.home_path)
        if authority is None: return UNCHECKED
        return None if committed_route_envelope(authority, entry) is not None else NOT_READY
    except Exception:
        return UNCHECKED
