"""One continuation bound to a verified owner turn in this chat."""
from datetime import datetime, timezone

from .model import Wake
from .schedule import parse_duration

DESCRIPTION = ("Resume work already underway in this conversation once, in 15 seconds to 15 minutes. "
               "Pass exactly one field: at to arm, or cancel with a returned ID. "
               "Arming returns id, armed=true, and due_at as an absolute ISO 8601 UTC timestamp. "
               "at accepts relative durations such as 30s, 2 minutes, or 1m30s (15s–15m inclusive). "
               "Each call creates an independent timer; cancel an earlier ID explicitly to replace it. "
               "When due, it gives you another turn in the current conversation with a Follow-up fired signal showing the scheduled and current times. "
               "If this conversation already has a turn underway, the timer is consumed without queuing a continuation. "
               "Armed timers survive gateway restarts. /new orphans them so they cannot resume in the new conversation. "
               "Only an owner turn or its continuation may arm one. Requested continuations leave interruption tokens unchanged.")
SCHEMA = {'name': 'follow_up', 'description': DESCRIPTION, 'parameters': {
    'type': 'object', 'properties': {
        'at': {'type': 'string', 'description':'Relative duration, for example 30s, 2 minutes, or 1m30s. Bounds 15s–15m inclusive.'},
        'cancel': {'type': 'string', 'description':'Timer ID returned in this conversation. Repeated cancellation is safe and reports if it already started.'}},
    'minProperties': 1, 'maxProperties': 1, 'additionalProperties': False}}


def handle(tool, args, *, session_id='', **kwargs):
    e = tool.engine
    if not isinstance(args, dict) or set(args) not in ({'at'}, {'cancel'}):
        return {'error': 'supply exactly one of at or cancel'}
    session = tool.identity()
    if not session or not session_id:
        return {'error': 'missing_session'}
    key = session.session_key
    with e.store.atomic():
        if 'cancel' in args:
            wid = args['cancel']
            w = e.store.get_wake(wid) if isinstance(wid, str) else None
            if not w or w.session_key != key or 'continuation' not in w.trigger_json:
                return {'error': 'unknown_timer'}
            if w.fires:
                return {'id': wid, 'status': 'already_started'}
            if w.status in {'active', 'paused', 'proposed'}:
                e.store.cas_wake(wid, w.status, expected_version=w.version, status='cancelled', status_reason='owner_cancelled')
                e.cancel_occurrences(wid, 'cancelled')
            return {'id': wid, 'status': e.store.get_wake(wid).status}

        try:
            seconds = parse_duration(args['at']) if isinstance(args['at'], str) else 0
        except ValueError:
            seconds = 0
        if not 15 <= seconds <= 900:
            return {'error': 'at must be a relative duration from 15s through 15m inclusive'}
        if not session.enabled or e.paused():
            return {'error': 'session_off'}
        requests = getattr(e,'requests',None)
        if requests and session_id in requests.turns:
            return {'error':'verified_owner_turn_required'}
        flight = e.intake.flight_for(session_id, key)
        session = e.store.get_session(key)
        if session.current_session_id != session_id:
            return {'error':'wrong_session'}
        origin = None
        if flight and flight.session_id == session_id and not flight.invalid:
            parent = e.store.get_wake(flight.wake_id)
            occurrence = e.store.get_occurrence(flight.wake_id, flight.dedupe_key)
            if parent and occurrence and occurrence.state == 'started' and occurrence.attempt == flight.attempt:
                if flight.owner_replied and verified_owner(e, session_id, key):
                    origin = e.intake.owner_turn_refs[session_id]
                else:
                    origin = parent.trigger_json.get('continuation')
        elif not flight and verified_owner(e, session_id, key):
            origin = e.intake.owner_turn_refs[session_id]
        if not origin or origin['chat'] != key:
            return {'error': 'verified_owner_turn_required'}
        active = [w for w in e.store.list_wakes() if w.status in {'active', 'proposed'}]
        gate = e.policy.creation_gate(session_key=key, platform=session.platform, chat_type=session.chat_type,
                                      allow_gateway_injection=e.injection_allowed(), kind='at',
                                      active_count=sum(w.session_key == key for w in active), global_active_count=len(active))
        if not gate.allowed or gate.status != 'active':
            return {'error': gate.reason or 'needs_owner_ok'}
        origin = {field: origin[field] for field in ('chat', 'session', 'turn')}
        w = e.store.create_wake(Wake(key, 'Follow-up fired', 'at',
            platform=session.platform, chat_type=session.chat_type, chat_id=session.chat_id,
            armed_session_id=session_id, next_due_at=e.clock.now()+seconds, owner_requested=True,
            trigger_json={'kind': 'at', 'continuation': origin}))
    e.signal()
    return {'id': w.id, 'armed': True,
            'due_at': datetime.fromtimestamp(w.next_due_at, timezone.utc).isoformat()}


def verified_owner(engine, session_id, key):
    context = engine.intake.owner_turn_refs.get(session_id)
    session = engine.store.get_session(key)
    return (bool(context) and session is not None and session.busy_since is not None
            and context['chat'] == key
            and context['turn'] == engine.intake.turns.get(session_id))
