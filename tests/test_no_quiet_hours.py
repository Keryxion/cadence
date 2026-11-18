"""Cadence schedules work at all hours; old quiet settings have no authority."""
from dataclasses import fields
import json

import pytest
import yaml

from cadence import commands
from cadence.policy import Policy
from test_engine import engine, arm, pending, KEY
from test_commands import runtime


def test_quiet_settings_are_not_policy_or_manifest_settings():
    names = {field.name for field in fields(Policy)}
    assert not {'quiet_hours', 'quiet_hours_urgent'} & names
    with open('plugin.yaml') as manifest:
        assert not {'quiet_hours', 'quiet_hours_urgent'} & yaml.safe_load(manifest)['config_schema'].keys()


@pytest.mark.parametrize('kind', ['at', 'every', 'owner_silent', 'url'])
@pytest.mark.parametrize('urgent', [False, True])
def test_legacy_quiet_settings_and_chat_override_do_not_gate(engine, kind, urgent):
    e = engine
    e.policy = Policy.from_settings({'timezone': 'UTC', 'quiet_hours': '00:00-23:59',
                                    'quiet_hours_urgent': False}, clock=e.clock)
    e.store.set_meta('quiet:' + KEY, json.dumps({'until': e.clock.now() + 86400}))
    w = arm(e, kind, urgent=urgent, trigger_json={'check_every': 60})
    o = pending(e, w)
    assert e.gate(w, o, e.store.get_session(KEY)) == ('', False, None)
    assert e.message_hold_reason(w, e.store.get_session(KEY)) == ''
    assert 'Quiet hours' not in e.tool.receipt(w, e.store.get_session(KEY))


def test_quiet_command_and_status_are_removed(runtime):
    assert commands.handle('quiet for 3h', runtime).startswith('Error:')
    assert 'quiet' not in commands.HELP.lower()
    assert 'quiet' not in commands.handle('status', runtime).lower()


def test_legacy_quiet_deferral_does_not_delay_delivery(engine):
    e = engine
    w = arm(e)
    o = pending(e, w)
    e.store.connection.execute('UPDATE occurrences SET error=? WHERE wake_id=? AND dedupe_key=?',
                               ('quiet_hours', w.id, o.dedupe_key))
    e.store.set_meta('not_before:' + o.id, str(e.clock.now() + 86400))
    e.tick()
    assert len(e.ctx.calls) == 1
