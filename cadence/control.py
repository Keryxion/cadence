"""Owner controls for this gateway conversation; no agent tool grants consent."""
import json
import re
from .model import FINISHED_WAKE_STATUSES

HELP = ('/cadence status | desk | list | why <id> | approve <id> | '
        'pause|resume|delete <id> | budget <id> <minimum> <budget> | on|off | '
        'responsibility <JSON> | trigger <JSON> | name <name>')


def handle(raw, runtime):
    e = runtime.get_engine()
    e.refresh()
    manager = e.responsibilities
    session = e.tool.identity()
    if not session: return 'Cadence needs a messaging conversation.'
    words = raw.strip().split(maxsplit=1)
    action = words[0] if words else 'status'
    if action == 'cancel': action = 'delete'
    rest = words[1] if len(words)>1 else ''
    with e.store.atomic():
        if action == 'add':
            match=re.fullmatch(r'in (\S+) (.+)',rest)
            if not match: return 'Use /cadence trigger <JSON> for an explicit condition, or add in <delay> <instruction>.'
            result=manager.handle('trigger',{'action':'create','title':match[2][:80],
                'note':match[2],'when':{'kind':'at','at':'in '+match[1]}},owner=True)
            return json.dumps(result,ensure_ascii=False)
        if action in {'on', 'off'}:
            e.store.cas_session(session.session_key, {'enabled':session.enabled}, enabled=action == 'on')
            e.signal()
            return 'Cadence ' + action + ' for this conversation.'
        if action == 'desk': return manager.desk(session)
        if action == 'status':
            return 'Cadence: ' + json.dumps({'scheduler':e.status(), 'execution': manager.budgets.available(*manager.global_scope()),
                'notification_tokens': manager.notification_balance(), 'enabled':session.enabled,
                'settings': e.settings_notice(), 'injection_allowed':e.injection_allowed(),
                'consent_help':None if e.injection_allowed() else 'Enable gateway injection in owner configuration'}, ensure_ascii=False) + '\n' + manager.desk(session) + ('\n'+e.settings_notice() if e.settings_notice() else '') + ('' if e.injection_allowed() else '\nplugins:\n  entries:\n    cadence:\n      allow_gateway_injection: true')
        if action == 'name': return runtime.request({'action':'rename','name':rest})
        if action in {'responsibility','trigger'}:
            try: args = json.loads(rest)
            except ValueError: return 'Supply a JSON object. ' + HELP
            return json.dumps(manager.handle(action,args,owner=True))
        if action == 'list':
            return json.dumps({name:manager.handle(name,{'action':'list'},owner=True) for name in ('responsibility','trigger')})
        w = e.store.get_wake(rest.split()[0]) if rest else None
        if not w or w.session_key != session.session_key or not w.managed:
            return HELP if action in {'help','status'} else 'Unknown item in this conversation. ' + HELP
        surface = 'responsibility' if w.role else 'trigger'
        if action == 'approve':
            if w.status != 'proposed': return 'Only proposed work requires approval.'
            if not e.policy.enabled or not session.enabled or not e.injection_allowed():
                return 'Enable Cadence and gateway injection consent before approval.'
            if w.responsibility_id and not w.role:
                parent = e.store.get_wake(w.responsibility_id)
                if not parent or parent.status in FINISHED_WAKE_STATUSES: return 'The responsibility has ended.'
            e.store.cas_wake(w.id,'proposed',status='active',status_reason='')
            if w.role:
                r=manager.load(w.id)
                r['fallback_credit']=0
                r['fallback_updated']=e.clock.now()
                if r['initial_at'] is not None: r['initial_at']=max(e.clock.now(),r['initial_at'])
                manager.save(r)
            e.signal()
            return manager.result(e.store.get_wake(w.id))['receipt']
        if action == 'budget':
            parts=rest.split()
            if len(parts)!=3 or not w.role: return 'Use budget <responsibility id> <minimum> <budget>.'
            try: checks={'min_per_24h':int(parts[1]),'budget_per_24h':int(parts[2])}
            except ValueError: return 'Minimum and budget must be integers.'
            args={'action':'update','id':w.id,'checks':checks}
        else:
            args={'action':'get' if action == 'why' else action,'id':w.id}
        return json.dumps(manager.handle(surface,args,owner=True),ensure_ascii=False)
