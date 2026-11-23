"""Responsibility ownership and explicit triggers over the gateway delivery engine.

A responsibility owns the notebook and budget; its triggers only contribute
reasons to one check. Temporary holds retain those reasons without spending.
"""
from dataclasses import asdict, replace
import json
import math
import uuid

from .budgets import Budgets
from .clock import format_timestamp
from .model import Wake, KINDS, PROBE_KINDS, EVENT_KINDS, FINISHED_WAKE_STATUSES
from .schedule import parse_at, parse_duration


def obj(properties, required=()):
    return {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False}


STRING = {'type': 'string'}
TEXT = {'type': 'string', 'minLength': 1}
BOOL = {'type': 'boolean'}
CHECKS = obj({'min_per_24h': {'type': 'integer', 'minimum': 1},
              'budget_per_24h': {'type': 'integer', 'minimum': 1}}, ('min_per_24h', 'budget_per_24h'))
UNTIL = obj({'expires': STRING, 'max_fires': {'type': 'integer', 'minimum': 1}, 'owner_replies': BOOL})
# Each alternative is complete: a kind alone is sufficient only for named events.
WHEN_FIELDS = {
    'at': ({'at': {**TEXT,'description':'ISO timestamp, local HH:MM, tomorrow HH:MM, or a relative delay such as in 10m.'}}, ('at',)),
    'every': ({'every': TEXT, 'at': TEXT}, ('every',)),
    'cron': ({'cron': TEXT}, ('cron',)),
    'owner_silent': ({'after': TEXT}, ('after',)),
    'file': ({'path': TEXT, 'pattern': STRING}, ('path',)),
    'process': ({'pid': {'type': 'integer', 'minimum': 1}}, ('pid',)),
    'url': ({'url': TEXT, 'pattern': STRING}, ('url',)),
    'command': ({'command': {'type': 'array', 'items': TEXT, 'minItems': 1}, 'cwd': TEXT,
                 'fire_on': {'enum': ['change', 'success', 'failure', 'json']}}, ('command',)),
    'startup': ({}, ()),
    'kanban_completed': ({'task_id': TEXT, 'board': TEXT}, ()),
    'kanban_blocked': ({'task_id': TEXT, 'board': TEXT}, ()),
    'kanban_worker_exited': ({'task_id': TEXT, 'board': TEXT}, ()),
    'subagent_done': ({}, ()), 'api_error': ({}, ()),
    'reaction': ({'emojis': {'type': 'array', 'items': TEXT}}, ()),
    'message_edited': ({}, ()),
}
WHEN_VARIANTS = []
for kind, (properties, required) in WHEN_FIELDS.items():
    properties = dict(properties)
    if kind in PROBE_KINDS:
        properties['check_every'] = TEXT
    if kind in PROBE_KINDS | EVENT_KINDS and kind != 'startup':
        properties['deadline'] = TEXT
    WHEN_VARIANTS.append(obj({'kind': {'const': kind}, **properties}, ('kind', *required)))
WHEN = {'oneOf': WHEN_VARIANTS}
R_FIELDS = {'title': {**TEXT,'maxLength':80}, 'charter': {**TEXT,'maxLength':2000},
            'notes': {**STRING,'maxLength':16000}, 'checks': CHECKS}
T_FIELDS = {'when': WHEN, 'title': {**TEXT,'maxLength':80}, 'note': {**TEXT,'maxLength':2000}, 'until': UNTIL}


def tool_schema(name, fields, variants, description):
    alternatives = []
    for action, (required, optional) in variants.items():
        allowed = dict.fromkeys((*required, *optional))
        schema = obj({'action': {'const': action}, **{k: fields[k] for k in allowed}}, ('action', *required))
        if action == 'update':
            schema['anyOf'] = [{'required': [k]} for k in optional]
        if name == 'trigger' and action == 'create':
            schema['anyOf'] = [{'required': ['responsibility_id']}, {'required': ['title', 'note']}]
        alternatives.append(schema)
    # Hermes removes root oneOf/anyOf/allOf before tool discovery and provider
    # requests. Publish ordinary properties and retain each action's closed shape
    # in conditionals, which survive that normalization.
    actions = '; '.join(f"{action}: requires {', '.join(required) or 'no other fields'}; "
                        f"optional {', '.join(optional) or 'none'}"
                        for action, (required, optional) in variants.items())
    published = {key for required, optional in variants.values() for key in (*required, *optional)}
    parameters = obj({'action': {'type': 'string', 'enum': list(variants), 'description': actions},
                      **{key: value for key, value in fields.items() if key in published}}, ('action',))
    conditional = alternatives[-1]
    for alternative in reversed(alternatives[:-1]):
        conditional = {'if': {'properties': {'action': alternative['properties']['action']}, 'required': ['action']},
                       'then': alternative, 'else': conditional}
    parameters.update(conditional)
    return {'name': name, 'description': description, 'parameters': parameters}


R_ACTIONS = {
    'create': (('title', 'charter', 'checks'), ('notes', 'initial_at', 'owner_asked')),
    'list': ((), ('detailed',)), 'get': (('id',), ()),
    'update': (('id',), tuple(R_FIELDS)),
    'pause': (('id',), ()), 'resume': (('id',), ()),
    'finish': (('id', 'reason'), ()), 'delete': (('id',), ()),
}
T_ACTIONS = {
    'create': (('when',), ('responsibility_id', 'title', 'note', 'until', 'owner_asked')),
    'list': ((), ('responsibility_id', 'detailed')), 'get': (('id',), ()),
    'update': (('id',), tuple(T_FIELDS)),
    'pause': (('id',), ()), 'resume': (('id',), ()), 'delete': (('id',), ()),
}
COMMON = {'id': TEXT, 'reason': TEXT, 'detailed': BOOL, 'owner_asked': BOOL,
          'initial_at': TEXT, 'responsibility_id': TEXT}
RESPONSIBILITY_SCHEMA = tool_schema('responsibility', {**COMMON, **R_FIELDS}, R_ACTIONS,
    'Own standing work in this conversation. Create a charter, persistent notes, minimum fallback and token budget; '
    'inspect, change, pause, finish or delete it. Set explicit next opportunities with trigger. '
    'Useful silent work is welcome. Holds retain eligible work within owner budgets.')
TRIGGER_SCHEMA = tool_schema('trigger', {**COMMON, **T_FIELDS}, T_ACTIONS,
    'Give work in this conversation an explicit time or event condition. Attach multiple triggers to a responsibility '
    'or create a standalone reminder/watcher. Matching reasons share one responsibility check; temporary capacity holds retain work.')
RESPOND_SCHEMA = {'name': 'respond', 'description': 'Record the running check result and whether its final reply should be delivered. '
    'Useful silent work is progress. Notes belong to responsibility; next timing belongs to trigger.',
    'parameters': obj({'outcome': {'enum': ['progress', 'no_change', 'done', 'blocked', 'needs_attention']},
                       'notify': BOOL, 'summary': {'type': 'string', 'maxLength': 1024}}, ('outcome', 'notify'))}


def validate(value, schema):
    """The same strict contract is enforced even when a host skips schema validation."""
    if 'oneOf' in schema:
        errors = []
        for candidate in schema['oneOf']:
            try:
                validate(value, candidate)
                return
            except ValueError as exc:
                errors.append(str(exc))
        raise ValueError('No valid action/condition shape: ' + '; '.join(dict.fromkeys(errors)))
    if 'const' in schema and value != schema['const']:
        raise ValueError('invalid action or trigger kind')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError('invalid option')
    kind = schema.get('type')
    valid = {'object': isinstance(value, dict), 'string': isinstance(value, str),
             'boolean': isinstance(value, bool), 'integer': isinstance(value, int) and not isinstance(value, bool),
             'array': isinstance(value, list)}
    if kind and not valid.get(kind, False):
        raise ValueError(f'expected {kind}')
    if kind == 'object' or 'properties' in schema:
        missing = set(schema.get('required', ())) - value.keys()
        unknown = value.keys() - schema['properties'].keys() if schema.get('additionalProperties') is False else set()
        if missing or unknown:
            raise ValueError(f'missing fields: {sorted(missing)}; unknown fields: {sorted(unknown)}')
        for k, v in value.items():
            if k in schema['properties']: validate(v, schema['properties'][k])
    if kind == 'array':
        if len(value) < schema.get('minItems', 0): raise ValueError('empty array')
        for v in value: validate(v, schema['items'])
    if kind == 'string':
        if schema.get('minLength') and not value.strip(): raise ValueError('empty text')
        if len(value) > schema.get('maxLength', math.inf): raise ValueError('text too long')
    if kind == 'integer' and value < schema.get('minimum', -math.inf): raise ValueError('integer below minimum')
    if 'anyOf' in schema and not any(set(v.get('required', ())) <= value.keys() for v in schema['anyOf']):
        raise ValueError('supply the required target or at least one field to change')
    if 'if' in schema:
        try:
            validate(value, schema['if'])
        except ValueError:
            branch = 'else'
        else:
            branch = 'then'
        if branch in schema: validate(value, schema[branch])


class Responsibilities:
    def __init__(self, engine):
        self.engine, self.store = engine, engine.store
        self.budgets = Budgets(self.store)
        with self.store.atomic():
            self.store.connection.execute('CREATE TABLE IF NOT EXISTS responsibilities (id TEXT PRIMARY KEY, document TEXT NOT NULL)')
            name,cap,rate=self.notification_scope()
            self.budgets.balance(name,cap,rate,initial=min(cap,self.engine.policy.interruption_initial))

    def load(self, rid):
        row = self.store.connection.execute('SELECT document FROM responsibilities WHERE id=?', (rid,)).fetchone()
        return json.loads(row[0]) if row else None

    def save(self, r):
        self.store.connection.execute('INSERT INTO responsibilities VALUES (?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                                      (r['id'], json.dumps(r)))

    def records(self, key=None):
        records = [json.loads(row[0]) for row in self.store.connection.execute('SELECT document FROM responsibilities ORDER BY rowid')]
        return [r for r in records if key is None or self.store.get_wake(r['id']).session_key == key]

    def global_scope(self):
        p = self.engine.policy
        return ('execution', p.execution_capacity, p.execution_refill_per_hour / 3600)

    def scopes(self, w):
        scopes = [self.global_scope()]
        if w.managed and w.responsibility_id:
            r = self.load(w.responsibility_id)
            n = r['checks']['budget_per_24h']
            scopes.append(('responsibility:' + w.responsibility_id, n, n/86400))
        return scopes

    def ticket(self, o):
        return f'{o.id}:{o.attempt}'

    def clear_reservations(self):
        live = {self.ticket(o) for o in self.store.list_occurrences(state='claimed')}
        for row in self.store.connection.execute("SELECT DISTINCT ticket FROM reservations WHERE ticket NOT LIKE 'request:%' AND ticket NOT LIKE 'notification:%'").fetchall():
            if row[0] not in live: self.budgets.release(row[0])

    def hold(self, w, *, ticket=None):
        now = self.engine.clock.now()
        until = now
        reasons = []
        for name, capacity, rate in self.scopes(w):
            available = self.budgets.available(name, capacity, rate, ticket=ticket)
            if available < 1-1e-9:
                reasons.append('execution_bucket' if name == 'execution' else 'responsibility_bucket')
                held = self.store.connection.execute('SELECT COUNT(*) FROM reservations WHERE name=? AND ticket!=?', (name, ticket or '')).fetchone()[0]
                balance = self.budgets.balance(name, capacity, rate)
                until = max(until, now + max(0, 1+held-balance)/rate)
        return (','.join(reasons), until if reasons else None)

    def reserve(self, o):
        if not self.budgets.reserve(self.ticket(o), self.scopes(self.store.get_wake(o.wake_id))): return False
        for ref in json.loads(self.store.get_meta('contributors:' + o.id) or '[]'):
            self.store.claim(ref['id'],ref['key'],epoch=o.epoch,pid=o.pid)
        return True

    def refund_sources(self, o):
        self.budgets.release(self.ticket(o))
        for ref in json.loads(self.store.get_meta('contributors:' + o.id) or '[]'):
            source=self.store.get_occurrence(ref['id'],ref['key'])
            if source and source.state=='claimed':
                self.store.refund(source.wake_id,source.dedupe_key,attempt=source.attempt,error='shared_check_deferred')

    def start(self, o):
        w = self.store.get_wake(o.wake_id)
        session = self.store.get_session(w.session_key)
        reason,_,_=self.gate(w,o,session,starting=True)
        if reason: return False
        for ref in json.loads(self.store.get_meta('contributors:' + o.id) or '[]'):
            source=self.store.get_occurrence(ref['id'],ref['key'])
            trigger=self.store.get_wake(ref['id'])
            if not source or source.state!='claimed' or self.gate(trigger,source,session,source_only=True)[0]:
                self.refund_sources(o)
                return False
        if not self.budgets.start(self.ticket(o), self.scopes(w)):
            return False
        if w.role and w.managed:
            r = self.load(w.id)
            r['fallback_credit'], r['fallback_updated'] = 0, self.engine.clock.now()
            r['last_started_at'] = self.engine.clock.now()
            r['initial_at'] = None
            self.save(r)
            counted=set()
            for ref in json.loads(self.store.get_meta('contributors:' + o.id) or '[]'):
                trigger = self.store.get_wake(ref['id'])
                source = self.store.get_occurrence(ref['id'], ref['key'])
                if not trigger or not source or source.state != 'claimed': continue
                self.store.cas_occurrence(trigger.id, source.dedupe_key, 'claimed', 'superseded', attempt=source.attempt, error='shared_check:' + o.id)
                if trigger.id in counted: continue
                counted.add(trigger.id)
                self.store.cas_wake(trigger.id, trigger.status, expected_version=trigger.version,
                                    fires=trigger.fires+1, last_fired_at=self.engine.clock.now())
                trigger = self.store.get_wake(trigger.id)
                if trigger.kind == 'at' or trigger.max_fires and trigger.fires >= trigger.max_fires:
                    self.store.cas_wake(trigger.id, trigger.status, expected_version=trigger.version, status='done', status_reason='completed')
        return True

    def fallback(self, r):
        now = self.engine.clock.now()
        w = self.store.get_wake(r['id'])
        if w.status == 'active':
            elapsed = max(0, now-r['fallback_updated'])
            r['fallback_credit'] = min(1, r['fallback_credit'] + elapsed*r['checks']['min_per_24h']/86400)
        r['fallback_updated'] = max(now, r['fallback_updated'])
        return now + (1-r['fallback_credit'])*86400/r['checks']['min_per_24h']

    def collect(self):
        """Collect all current reasons before admission, preserving source identities.

        Source occurrences stay pending until the shared turn actually starts.
        New matches after claim cannot change that claim's contributor snapshot.
        """
        with self.store.atomic():
            self.clear_reservations()
            for pending in self.store.list_occurrences(state='pending'):
                if self.store.get_wake(pending.wake_id).role:
                    self.refund_sources(pending)
            for r in self.records():
                w = self.store.get_wake(r['id'])
                if w.status != 'active': continue
                self.fallback(r)
                self.save(r)
                if self.store.list_occurrences(w.id, state='claimed') or self.store.list_occurrences(w.id, state='started'): continue
                refs, payload = [], []
                if r['fallback_credit'] >= 1-1e-9:
                    payload.append({'fallback': True, 'instruction': 'Review this responsibility and fix its next scheduled time.'})
                for t in self.store.list_wakes(w.session_key, status='active'):
                    if not t.managed or t.role or t.responsibility_id != w.id: continue
                    for source in self.store.list_occurrences(t.id, state='pending'):
                        reason, _, _ = self.engine.gate(t, source, self.store.get_session(t.session_key), source_only=True)
                        if reason: continue
                        refs.append({'id': t.id, 'key': source.dedupe_key})
                        existing=next((entry for entry in payload if entry.get('trigger_id')==t.id),None)
                        if existing:
                            existing['payload']=(existing['payload']+source.payload_json)[-20:]
                        else:
                            payload.append({'trigger_id': t.id, 'kind': t.kind, 'instruction': self.store.get_meta('trigger_instruction:' + t.id) or '',
                                            'payload': source.payload_json})
                if r.get('initial_at') is not None and r['initial_at'] <= self.engine.clock.now():
                    payload.append({'initial': True})
                pending = self.store.list_occurrences(w.id, state='pending')
                if not payload:
                    for old in pending:
                        self.store.cas_occurrence(w.id, old.dedupe_key, 'pending', 'superseded', error='reasons_removed')
                    continue
                key = pending[0].dedupe_key if pending else 'r:' + uuid.uuid4().hex
                # Bound source payloads independently; keep every contributing ID/instruction.
                # The full contributor list is durable even if prompt payloads are clipped.
                self.store.set_meta('contributors:' + w.id + '/' + key, json.dumps(refs))
                self.store.set_meta('reasons:' + w.id + '/' + key, json.dumps(payload))
                if not pending: self.store.add_occurrence(w.id, key)

    def gate(self, w, o, session, *, source_only=False, starting=False):
        e, now = self.engine, self.engine.clock.now()
        if w.status == 'paused': return 'paused', True, None
        if w.status != 'active': return 'inactive', False, None
        if w.expires_at is not None and now >= w.expires_at: return 'expired', False, None
        if w.max_fires is not None and w.fires >= w.max_fires: return 'max_fires', False, None
        if not session: return 'missing_session', True, None
        if w.cancel_on_reply and session.last_human_at is not None and session.last_human_at > w.created_at:
            return 'cancel_on_reply', False, None
        if w.kind=='owner_silent' and o.dedupe_key.startswith('s:') and o.dedupe_key!='s:'+(session.episode_id or ''):
            return 'episode_ended',False,None
        if not session.enabled: return 'session_off', True, None
        if not e.family_enabled(w): return 'source_disabled_or_responsibility_paused', True, None
        if source_only: return '', False, None
        if not e.policy.enabled or e.paused(): return 'emergency_stop', True, None
        if not e.injection_allowed(): return 'injection_disabled', True, None
        from .policy import gateway_platform
        if not gateway_platform(session.platform): return 'non_gateway', False, None
        if e.policy.dm_only and session.chat_type != 'dm': return 'dm_only', False, None
        if session.paused_until and session.paused_until > now: return 'session_paused', True, session.paused_until
        origin = w.trigger_json.get('continuation')
        if origin:
            if session.busy_since is not None and not starting: return 'continuation_busy', False, None
            if (origin.get('chat') != session.session_key or not origin.get('turn') or
                    origin.get('session') != session.current_session_id and
                    e.compression_tip(origin.get('session')) != session.current_session_id):
                return 'continuation_context_missing', False, None
        health = json.loads(self.store.get_meta('provider_health') or '{}')
        trial=health.get('trial')
        if trial:
            wid,key=trial.split('/',1)
            live=self.store.get_occurrence(wid,key)
            if not live or live.state not in {'claimed','started'}:
                health.pop('trial',None)
                self.store.set_meta('provider_health',json.dumps(health))
                trial=None
        if health.get('until',0)>now or trial and not (starting and trial==o.id):
            return 'provider_unavailable',True,health.get('until')
        from .policy import owner_class
        if ((w.role or not owner_class(w)) and e.policy.daily_cost_limit_usd > 0 and
            self.store.agent_cost_today(w.session_key, e.policy.resolved_timezone())['cost_microusd']/1e6 >= e.policy.daily_cost_limit_usd):
            return 'daily_cost_cap', True, None
        not_before = float(self.store.get_meta('not_before:' + o.id) or 0)
        if not w.responsibility_id and not origin and not w.trigger_json.get('own_time'):
            from .policy import is_watcher, owner_class, one_shot
            mute=e.policy.unanswered_gate(w,session.unanswered_count)
            if mute: return mute,mute.startswith('held_'),None
            if self.notification_balance() < 1-1e-9 and not (owner_class(w) and one_shot(w)):
                return ('held_interruptions',True,None) if is_watcher(w) else ('interruption_limit',False,None)
        if not_before > now and 'bucket' not in o.error:
            return 'not_before', True, not_before
        if session.busy_since is not None and not starting: return 'busy', True, None
        if not starting and (self.store.list_occurrences(session_key=w.session_key, state='claimed') or self.store.list_occurrences(session_key=w.session_key, state='started')):
            return 'in_flight', True, None
        reason, until = self.hold(w,ticket=self.ticket(o) if starting else None)
        return reason, bool(reason), until

    def inspect(self, w):
        now = self.engine.clock.now()
        r = self.load(w.id) if w.role else None
        reason, until = self.hold(w) if w.role or not w.responsibility_id else ('', None)
        pending = self.store.list_occurrences(w.id, state='pending')
        if not pending and r and self.fallback(r)<=now:
            from .model import Occurrence
            pending=[Occurrence(w.id,'inspect')]
        if pending:
            gate, _, gate_until = self.engine.gate(w, pending[0], self.store.get_session(w.session_key))
            reason = gate or reason
            until = max(until or now, gate_until or now) if until or gate_until else None
        record = {'id': w.id, 'status': w.status, 'title': w.title,
                  'owner_asked': w.owner_requested, 'hold_reason': reason or w.status_reason or None,
                  'next_eligible_at': format_timestamp(until) if until else None,
                  'started_checks': w.fires, 'latest_result': None,
                  'usage':{name:getattr(w,name) for name in ('model_turns','tokens_in','tokens_out','cache_read_tokens','cache_write_tokens','cost_microusd','unpriced_calls')},
                  'occurrences':[{'state':o.state,'hold_reason':o.error or None} for o in self.store.list_occurrences(w.id) if o.state in {'pending','claimed','started'}]}
        history = [o for o in self.store.list_occurrences(w.id) if o.started_at is not None]
        if history:
            last = history[-1]
            record['latest_result'] = {'outcome': last.outcome, 'summary': last.summary, 'state': last.state}
        if r:
            due = self.fallback(r)
            self.save(r)
            n = r['checks']['budget_per_24h']
            record.update(charter=w.note, notes=r['notes'], checks=r['checks'],
                bucket={'capacity': n, 'refill_per_hour': n/24,
                        'balance': self.budgets.balance('responsibility:' + w.id, n, n/86400)},
                next_fallback_at=format_timestamp(due) if w.status == 'active' else None,
                initial_at=format_timestamp(r['initial_at']) if r.get('initial_at') is not None else None,
                missed_minimum=bool(r['fallback_credit'] >= 1-1e-9 and reason),
                triggers=[t.id for t in self.store.list_wakes(w.session_key) if t.managed and not t.role and t.responsibility_id == w.id])
        else:
            record.update(when=self.public_when(w), note=(self.store.get_meta('trigger_instruction:' + w.id) or None) if w.responsibility_id else w.note, responsibility_id=w.responsibility_id or None,
                          until={'expires':format_timestamp(w.expires_at) if w.expires_at is not None else None,
                                 'max_fires':w.max_fires,'owner_replies':w.cancel_on_reply},
                          next_due_at=format_timestamp(w.next_due_at) if w.next_due_at is not None else None,
                          deadline=format_timestamp(w.deadline_at) if w.deadline_at is not None else None)
        return record

    def creation_gate(self, session, kind, sid, *, owner=False):
        e = self.engine
        if not session.enabled: raise ValueError('This conversation is off; the owner can enable it with /cadence on.')
        flight = e.intake.flight_for(sid, session.session_key)
        parent = self.store.get_wake(flight.wake_id) if flight else None
        child_key = e.child_key(flight) if flight else ''
        children = int(self.store.get_meta(child_key) or 0) if child_key else 0
        active = [w for w in self.store.list_wakes() if w.status in {'active', 'proposed'}]
        gate = e.policy.creation_gate(session_key=session.session_key, platform=session.platform, chat_type=session.chat_type,
            allow_gateway_injection=e.injection_allowed(), kind=kind, creator='user' if owner else 'agent',
            created_in='wake_turn' if flight else 'human_turn', parent_role=bool(parent and parent.role),
            depth=1 if parent and parent.role else parent.depth+1 if parent else 0,
            untrusted_payload=bool(flight and flight.untrusted), children_created=children,
            active_count=sum(w.session_key == session.session_key for w in active), global_active_count=len(active))
        if not gate.allowed: raise ValueError(gate.reason + ': ' + (gate.detail or 'Review the owner configuration or active work.'))
        if child_key: self.store.set_meta(child_key, str(children+1))
        return gate.status

    def handle(self, tool, args, *, session_id='', owner=False, **metadata):
        schemas = {'responsibility': RESPONSIBILITY_SCHEMA, 'trigger': TRIGGER_SCHEMA, 'respond': RESPOND_SCHEMA}
        try:
            from .intake import delegated_child
            if delegated_child(metadata.get('platform','')):
                raise ValueError('Cadence tools belong to the parent conversation turn.')
            validate(args, schemas[tool]['parameters'])
            self.engine.refresh()
            if tool == 'respond': return self.respond(args, session_id)
            session = self.engine.tool.identity()
            if not session: raise ValueError('A messaging conversation is required.')
            with self.store.atomic():
                return self.manage(tool, args, self.store.get_session(session.session_key), session_id, owner)
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            return {'error': 'invalid_request', 'detail': str(exc), 'receipt': 'Not changed. ' + str(exc)}

    def manage(self, tool, a, session, sid, owner):
        e, s, action = self.engine, self.store, a['action']
        is_r = tool == 'responsibility'
        if action == 'list':
            wakes = [w for w in s.list_wakes(session.session_key) if w.managed and w.role == is_r
                     and 'continuation' not in w.trigger_json]
            if 'responsibility_id' in a:
                self.owned(a['responsibility_id'], session, True)
                wakes = [w for w in wakes if w.responsibility_id == a['responsibility_id']]
            if not a.get('detailed'): wakes = [w for w in wakes if w.status not in FINISHED_WAKE_STATUSES]
            wakes.sort(key=lambda w: (w.status != 'active', not w.owner_requested, w.created_at))
            items=[self.inspect(w) for w in wakes]
            if not a.get('detailed'):
                compact={'id','status','title','owner_asked','checks','bucket','next_due_at','next_fallback_at','hold_reason','next_eligible_at','latest_result','started_checks'}
                items=[{k:v for k,v in item.items() if k in compact} for item in items]
            return {'ok': True, 'items':items}
        if action == 'create':
            flight=e.intake.flight_for(sid,session.session_key)
            if is_r and flight and flight.untrusted:
                raise ValueError('Untrusted source data cannot authorize a new standing responsibility; continue within the existing charter.')
            evidence = owner or e.tool.owner_turn_evidence(sid, flight)
            if a.get('owner_asked') and not evidence: raise ValueError('owner_asked requires a verified owner request.')
            parent = self.owned(a['responsibility_id'], session, True) if 'responsibility_id' in a else None
            if parent and parent.status in FINISHED_WAKE_STATUSES: raise ValueError('Attach to live work or create a new responsibility.')
            kind = 'at' if is_r else a['when']['kind']
            status = self.creation_gate(session, kind, sid, owner=owner)
            ancestor=s.get_wake(flight.wake_id) if flight else None
            depth=1 if ancestor and ancestor.role else ancestor.depth+1 if ancestor else 0
            wid = ('r_' if is_r else 't_') + uuid.uuid4().hex[:16]
            w = Wake(session.session_key, a.get('charter') if is_r else a.get('note') or parent.note,
                kind, id=wid, title=a.get('title') or parent.title, role=is_r, managed=True,
                responsibility_id=wid if is_r else parent.id if parent else '',
                platform=session.platform, chat_type=session.chat_type, chat_id=session.chat_id,
                armed_session_id=sid or session.current_session_id, status=status,
                created_in='wake_turn' if flight else 'human_turn',depth=depth,
                parent_wake_id=ancestor.id if ancestor else None,
                creator='user' if owner else 'agent', owner_requested=bool(a.get('owner_asked') or owner))
            if is_r:
                self.check_limits(a['checks'])
                r = {'id': wid, 'notes': a.get('notes', ''), 'checks': a['checks'],
                     'fallback_credit': 0, 'fallback_updated': e.clock.now(),
                     'initial_at': self.parse_time(a['initial_at']) if 'initial_at' in a else e.clock.now()}
                self.save(r)
            else:
                w = self.prepare(w, a)
            s.create_wake(w)
            if not is_r: s.set_meta('trigger_instruction:' + w.id,a.get('note','') if parent else w.note)
            e.signal()
            return self.result(s.get_wake(wid))
        w = self.owned(a['id'], session, is_r)
        if not is_r and action in {'update','pause','delete'}: self.invalidate_snapshot(w.id)
        if action == 'get': return self.result(w)
        if w.trigger_json.get('builtin'):
            raise ValueError('This opportunity is controlled by owner settings, not trigger mutations.')
        r = self.load(w.id) if is_r else None
        if r: self.fallback(r)
        if action in {'delete', 'finish'}:
            if w.status not in {'done', 'cancelled'}:
                self.end(w, 'done' if action == 'finish' else 'cancelled', a.get('reason', 'removed'))
        elif action == 'pause':
            if is_r:
                for queued in s.list_occurrences(w.id,state='claimed'):
                    self.refund_sources(queued)
                    s.refund(w.id,queued.dedupe_key,attempt=queued.attempt,error='paused')
            if w.status == 'active': s.cas_wake(w.id, w.status, status='paused', status_reason='owner' if owner else 'agent')
        elif action == 'resume':
            if w.status != 'paused': raise ValueError('Only paused work can be resumed; proposals require owner approval.')
            if w.status_reason.startswith('governor:') and not owner:
                raise ValueError('Persistent errors require owner review: use /cadence why then /cadence resume.')
            if not e.injection_allowed() or not session.enabled or not e.policy.enabled: raise ValueError('Enable this conversation and injection consent before resuming.')
            s.cas_wake(w.id, 'paused', status='active', status_reason='')
        elif action == 'update':
            if w.status in FINISHED_WAKE_STATUSES: raise ValueError('Create new work instead of changing finished work.')
            changes = {}
            for field in ('title', 'charter'):
                if field in a: changes['note' if field == 'charter' else field] = a[field]
            if is_r:
                if 'checks' in a:
                    self.check_limits(a['checks'])
                    if not owner and (a['checks']['min_per_24h'] < r['checks']['min_per_24h'] or
                                      a['checks']['budget_per_24h'] > r['checks']['budget_per_24h']):
                        raise ValueError('Only the owner may lower the required minimum or raise this budget.')
                    old = r['checks']['budget_per_24h']
                    self.budgets.balance('responsibility:' + w.id, old, old/86400)
                    r['checks'] = a['checks']
                if 'notes' in a: r['notes'] = a['notes']
            else:
                prepared = self.prepare(w, a)
                if 'when' in a: self.engine.cancel_occurrences(w.id,'condition_changed',preserve_started=True)
                if 'note' in a: s.set_meta('trigger_instruction:' + w.id,a['note'])
                changes = {k: v for k, v in asdict(prepared).items() if getattr(w, k) != v and k not in {'id', 'session_key', 'version'}}
                if not owner and set(a) & {'when','note','until'}:
                    changes.update(agent_edited=True,owner_requested=False)
            # Let the store enforce invariant text bounds before writing notebooks.
            if changes:
                candidate = replace(w, **changes)
                from .store import _validate_wake
                _validate_wake(candidate)
                s.cas_wake(w.id, w.status, expected_version=w.version, **changes)
        if r:
            r['fallback_updated'] = e.clock.now()
            self.save(r)
        e.signal()
        return self.result(s.get_wake(w.id))

    def parse_time(self, value):
        try: return self.engine.clock.now()+parse_duration(value)
        except ValueError:
            return parse_at(value, now=self.engine.clock.now(), timezone=self.engine.policy.resolved_timezone())

    def check_limits(self, checks):
        if checks['min_per_24h'] > checks['budget_per_24h']:
            raise ValueError('min_per_24h must not exceed budget_per_24h.')
        if checks['budget_per_24h'] > self.engine.policy.responsibility_budget_max:
            raise ValueError(f'budget_per_24h exceeds owner limit {self.engine.policy.responsibility_budget_max}.')

    def owned(self, wid, session, responsibility):
        w = self.store.get_wake(wid)
        if not w or w.session_key != session.session_key or not w.managed or w.role != responsibility or 'continuation' in w.trigger_json:
            raise ValueError('Unknown item in this conversation.')
        return w

    @staticmethod
    def public_when(w):
        when=dict(w.trigger_json)
        if isinstance(when.get('check_every'),(int,float)):
            when['check_every']=f"{when['check_every']:g}s"
        return when

    def prepare(self, w, a):
        when = a.get('when', self.public_when(w))
        # Validate even if an edit only changes instructions.
        validate(when, WHEN)
        for field in ('every', 'after', 'check_every'):
            if field in when and parse_duration(when[field]) <= 0: raise ValueError(f'{field} must be positive.')
        if when['kind']=='at':
            when={**when,'at':format_timestamp(self.parse_time(when['at']))}
        request = {'trigger': when}
        for key in ('title', 'note', 'until'):
            if key in a: request[key] = a[key]
        result = self.engine.tool.prepare(w, request, reschedule='when' in a)
        self.store.set_meta('adjustments:' + w.id,json.dumps(result.clamped))
        return result.wake

    def result(self, w):
        record = self.inspect(w)
        receipt = ('Not armed. Owner approval required: /cadence approve ' + w.id if w.status == 'proposed' else
                   'Accepted. ' + w.status + ('. Waiting: ' + record['hold_reason'] if record['hold_reason'] else '.'))
        adjustments=json.loads(self.store.get_meta('adjustments:' + w.id) or '{}')
        if adjustments: receipt += ' Adjusted: ' + json.dumps(adjustments) + '.'
        if record.get('next_due_at'): receipt += ' Next due ' + record['next_due_at'] + '.'
        return {'ok': True, 'id': w.id, 'status': w.status, 'armed': w.status == 'active',
                'receipt': receipt, 'record': record, 'adjustments':adjustments,
                'cache':self.engine.tool.cache_result(w)}

    def invalidate_snapshot(self, trigger_id):
        """A queued envelope must not authorize work its owner has just changed."""
        for o in self.store.list_occurrences(state='claimed'):
            w=self.store.get_wake(o.wake_id)
            if not w.role or not w.managed: continue
            refs=json.loads(self.store.get_meta('contributors:' + o.id) or '[]')
            if not any(ref['id']==trigger_id for ref in refs): continue
            self.refund_sources(o)
            self.store.refund(o.wake_id,o.dedupe_key,attempt=o.attempt,error='trigger_changed')
            self.store.set_meta('accepted:' + o.id,'0')
            self.store.set_meta('not_before:' + o.id,'')

    def end(self, w, status, reason):
        self.store.cas_wake(w.id, w.status, status=status, status_reason=reason)
        self.engine.cancel_occurrences(w.id, reason, preserve_started=True)
        for occurrence in self.store.list_occurrences(w.id,state='started'):
            self.store.update_occurrence(w.id,occurrence.dedupe_key,'started',attempt=occurrence.attempt,force_silent=True)
        for t in self.store.list_wakes(w.session_key):
            if t.id != w.id and t.managed and t.responsibility_id == w.id and t.status not in FINISHED_WAKE_STATUSES:
                self.store.cas_wake(t.id, t.status, status='cancelled', status_reason='responsibility_ended')
                self.engine.cancel_occurrences(t.id, reason, preserve_started=True)

    def respond(self, a, sid):
        session = self.engine.tool.identity()
        f = self.engine.intake.flight_for(sid, session.session_key) if session else None
        if not f or f.invalid or f.session_id != sid: return {'error': 'not_in_flight'}
        w = self.store.get_wake(f.wake_id)
        if a['outcome'] == 'done' and w.role and not a.get('summary', '').strip():
            raise ValueError('Completing a responsibility requires a summary explaining why.')
        return self.engine.tool.respond(a, f)

    def finished(self, w, o):
        if w.status not in {'active','paused'}: return
        if w.role:
            if o.outcome == 'done': self.end(w, 'done', o.summary)
        elif w.kind == 'at' or o.outcome == 'done':
            self.store.cas_wake(w.id, w.status, status='done', status_reason='completed')

    def notification_scope(self):
        p = self.engine.policy
        return ('notifications', p.interruption_capacity, 1/p.interruption_refill_seconds)

    def notification_balance(self):
        name, cap, rate = self.notification_scope()
        return self.budgets.available(name, cap, rate, initial=min(cap, self.engine.policy.interruption_initial))

    def allow_notification(self, w, o, session):
        if 'continuation' in w.trigger_json or w.owner_requested and not w.role: return True
        if session.unanswered_count >= self.engine.policy.max_unanswered: return False
        return self.budgets.reserve('notification:' + self.ticket(o), [self.notification_scope()])

    def settle_notification(self, o, delivered):
        ticket = 'notification:' + self.ticket(o)
        if delivered and self.store.connection.execute('SELECT 1 FROM reservations WHERE ticket=?', (ticket,)).fetchone():
            self.budgets.start(ticket, [self.notification_scope()])
        self.budgets.release(ticket)

    def desk(self, session, *, before_start=False):
        with self.store.atomic(): return self._desk(session, before_start=before_start)

    def _desk(self, session, *, before_start=False):
        rows = (["Pre-start snapshot: this turn's token charges and fallback reset are not included. "
                 "Use responsibility.get for current values during the check."] if before_start else [])
        rows.append('Your responsibilities:')
        for r in self.records(session.session_key):
            w = self.store.get_wake(r['id'])
            if w.status not in {'active', 'paused'}: continue
            record = self.inspect(w)
            rows.append(f"- {w.id} {w.title}: {w.note[:160]} | {w.status} | fallback {record['next_fallback_at']} | "
                        f"tokens {record['bucket']['balance']:.2f}/{record['bucket']['capacity']} | {record['hold_reason'] or 'ready'}")
        active=[w for w in self.store.list_wakes(session.session_key) if w.status=='active' and not w.role]
        due=[w.next_due_at for w in active if w.next_due_at is not None]
        rows.append(f"Other active triggers: {len(active)}; next timed opportunity: {format_timestamp(min(due)) if due else 'none'}")
        rows.append(f"Owner last wrote: {format_timestamp(session.last_human_at) if session.last_human_at else 'unknown'}; unanswered: {session.unanswered_count}")
        rows.append(f"Profile execution tokens: {self.budgets.available(*self.global_scope()):.2f}; notification tokens: {self.notification_balance():.2f}")
        cost=self.store.agent_cost_today(session.session_key,self.engine.policy.resolved_timezone())
        rows.append(f"Priced agent cost today: ${cost['cost_microusd']/1e6:.2f}; unpriced calls: {cost['unpriced_calls']}")
        return '\n'.join(rows)[:1800]
