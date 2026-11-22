"""Seed pre-role-policy schedules to exercise upgrade behavior in simulations."""
from dataclasses import asdict

from cadence.model import Wake


def seed_existing(engine, session, args):
    wake = Wake(session.session_key, args.get('note',''), args['trigger']['kind'],
                platform=session.platform, chat_type=session.chat_type, chat_id=session.chat_id,
                armed_session_id=session.current_session_id,
                status='proposed' if engine.policy.agent_can_create == 'ask_first' else 'active')
    try:
        result = engine.tool.prepare(wake,args)
    except ValueError as exc:
        return {'error':'invalid_request','detail':str(exc)}
    wake = engine.store.create_wake(result.wake)
    return {'ok':True,'armed':wake.status=='active','wake':asdict(wake),
            'clamped':result.clamped,'cache':engine.tool.cache_result(wake),'receipt':engine.tool.receipt(wake,session)}
