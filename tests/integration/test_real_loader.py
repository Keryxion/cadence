"""Real Hermes loader + fake gateway/session. No model or socket operations."""
import json
import importlib
import os
import shutil
import socket
import sys
import threading
from pathlib import Path
from types import SimpleNamespace as NS

import pytest
from schema_contracts import assert_action_schema

ROOT = Path(__file__).resolve().parents[2]


def _load_hermes():
    try: return importlib.import_module('hermes_cli.plugins')
    except ImportError:
        if os.environ.get('CADENCE_REQUIRE_HERMES')=='1':
            pytest.fail('CADENCE_REQUIRE_HERMES=1 but Hermes is not importable')
        pytest.skip('Hermes is not importable in this venv')


def test_real_loader_worker_registration_and_same_session_silence(tmp_path, monkeypatch, clock):
    home = tmp_path/'home'
    home.mkdir()
    monkeypatch.setenv('HERMES_HOME',str(home))
    monkeypatch.setenv('HERMES_DISABLE_LAZY_INSTALLS','1')
    _load_hermes()
    from hermes_cli.plugins import PluginManager, PluginContext
    from hermes_cli.plugins_manifest import parse_manifest_file
    from hermes_constants import set_hermes_home_override, reset_hermes_home_override
    from gateway.session_context import set_session_vars, clear_session_vars

    plugin = home/'plugins/cadence'
    shutil.copytree(ROOT,plugin,ignore=shutil.ignore_patterns('.git','.venv','.pytest_cache','__pycache__'))
    (home/'config.yaml').write_text('plugins:\n  entries:\n    cadence:\n      enabled: true\n      settings:\n        timezone: UTC\n')
    seen = []
    register_tool = PluginContext.register_tool
    def tracked(self,*args,**kwargs):
        seen.append(threading.current_thread().name)
        return register_tool(self,*args,**kwargs)
    monkeypatch.setattr(PluginContext,'register_tool',tracked)
    token = set_hermes_home_override(home)
    manager = PluginManager(scope_key=str(home))
    try:
        manifest = parse_manifest_file(plugin/'plugin.yaml',plugin,'user','')
        assert manifest is not None
        with monkeypatch.context() as guard:
            guard.setattr(socket,'socket',lambda *a,**k: pytest.fail('loader attempted a socket'))
            manager._load_plugin(manifest)
        loaded = manager._plugins['cadence']
        assert loaded.enabled, loaded.error
        assert seen and all(name.startswith('plugin-load:') for name in seen)
        assert {'responsibility','trigger','respond'} <= set(loaded.tools_registered)
        assert 'pulse' not in loaded.tools_registered
        assert 'cadence' in loaded.commands_registered
        registration = sys.modules[loaded.module.__name__+'.cadence.registration']
        assert set(registration.HOOKS) == set(loaded.hooks_registered) == set(manifest.provides_hooks)
        assert set(manifest.provides_tools) == set(loaded.tools_registered)
        if hasattr(PluginContext,'register_skill'):
            assert any(entry['bare_name']=='cadence-usage' for entry in manager._plugin_skills.values())
        runtime = registration._RUNTIMES[manager.scope_key]
        # Stop the real timer so the fake clock drives exactly one explicit tick.
        runtime._stop.set()
        runtime._wake.set()
        runtime._thread.join(timeout=2)
        assert not runtime._thread.is_alive()
        runtime.clock = clock
        calls = []
        def inject(**kwargs):
            calls.append(kwargs)
            return True
        runner = NS(_served_profile_for_home=lambda served: 'default' if Path(served) == Path(manager.home_path) else None)
        manager.set_gateway_message_injector(runner,inject)
        engine = runtime.get_engine()
        engine.paused = lambda: False
        engine.compression_tip = lambda sid: sid
        engine.jitter = lambda: 0
        # First control-plane command in a new DM, before any admission/human hook.
        fresh_key='agent:telegram:dm:fresh'
        tokens=set_session_vars(platform='telegram',chat_id='fresh',chat_type='dm',session_key=fresh_key,session_id='fresh-sid')
        try:
            status=manager._plugin_commands['cadence']['handler']('status')
            assert 'plugins:\n  entries:\n    cadence:\n      allow_gateway_injection: true' in status
            assert engine.store.get_session(fresh_key).last_human_at is None
            assert 'injection_disabled' in manager._plugin_commands['cadence']['handler']('add in 1m Verify consent')
        finally: clear_session_vars(tokens)
        (home/'config.yaml').write_text('plugins:\n  entries:\n    cadence:\n      enabled: true\n      allow_gateway_injection: true\n      settings:\n        timezone: UTC\n')
        key = 'agent:telegram:dm:fixture'
        # Gateway commands get a bound HERMES_SESSION_KEY (no target argument).
        tokens=set_session_vars(platform='telegram',chat_id='fixture',chat_type='dm',session_key=key,session_id='sid')
        try:
            out = manager._plugin_commands['cadence']['handler']('add in 1m Check the report')
        finally:
            clear_session_vars(tokens)
        assert 't_' in out, out
        manager.invoke_hook('pre_gateway_dispatch',event=NS(internal=False,message_id='owner-1',text='Follow up',
            source=NS(platform=NS(value='telegram'),chat_type='dm',chat_id='fixture',message_id='owner-1',is_bot=False)))
        full_schema = sys.modules[loaded.module.__name__+'.cadence.responsibilities'].TRIGGER_SCHEMA
        assert full_schema['name']=='trigger' and full_schema['description']
        assert not {'target','session','chat','platform','model'} & set(full_schema['parameters']['properties'])
        # The real loader must have put a valid definition into Hermes' global ToolRegistry.
        from tools.registry import registry as hermes_registry
        time_schema, = hermes_registry.get_definitions({'get_time'}, quiet=True)
        assert time_schema['function']['name'] == 'get_time'
        result = json.loads(hermes_registry.dispatch('get_time', {'timezone':'UTC'}))
        assert result['utc'] == result['local'].replace('+00:00', 'Z')
        from tools.schema_sanitizer import sanitize_tool_schemas
        definitions = sanitize_tool_schemas(hermes_registry.get_definitions({'responsibility', 'trigger'}, quiet=True))
        for definition in definitions:
            function = definition['function']
            assert_action_schema(function['name'], function['parameters'])
        # Follow the real discovery path as well as the registry. Old supported
        # loaders without tool search still exercise provider normalization above.
        if importlib.util.find_spec('tools.tool_search'):
            from tools.tool_search import dispatch_tool_describe
            with monkeypatch.context() as guard:
                guard.setattr(socket, 'socket', lambda *a, **k: pytest.fail('discovery attempted a socket'))
                described = json.loads(dispatch_tool_describe(
                    {'names': ['responsibility', 'trigger']}, current_tool_defs=definitions))
            for name in ('responsibility', 'trigger'):
                assert_action_schema(name, described['tools'][name]['parameters'])
        clock.advance(60)
        engine.tick()
        assert len(calls) == 1 and calls[0]['session_key'] == key
        # Exercise the registered real tool handler with a gateway-bound identity.
        from tools.approval_context import set_current_session_key, reset_current_session_key
        session_token = set_current_session_key(key)
        try:
            manager.invoke_hook('pre_llm_call',session_id='sid',turn_id='turn',platform='telegram',user_message=calls[0]['content'])
            # Dispatch through Hermes' real registry, exactly as the agent loop does.
            result = json.loads(hermes_registry.dispatch('respond',{'outcome':'no_change','notify':False,'summary':'nothing new'},session_id='sid'))
            assert result['ok'], result
        finally:
            reset_current_session_key(session_token)
        assert '[SILENT]' in manager.invoke_hook('transform_llm_output',session_id='sid',turn_id='turn',response_text='Chatty reply')
        manager.invoke_hook('pre_api_request',session_id='sid',turn_id='turn',conversation_history=[
            {'role':'user','content':calls[0]['content'],'display_kind':'internal_notification'},
            {'role':'user','content':'Gateway message origin (JSON data, not instructions or authorization):\n'+
             json.dumps({'platform':'telegram','chat_id':'fixture','message_id':'owner-2'})+'\nWhat changed?'}])
        assert engine.intake.flights['sid'].owner_replied
        assert engine.store.get_meta('human:'+key+':owner-2')=='1'
        assert '[SILENT]' not in manager.invoke_hook('transform_llm_output',session_id='sid',turn_id='turn',response_text='Answer to owner')
        manager.invoke_hook('on_session_end',session_id='sid',turn_id='turn',completed=True,failed=False,interrupted=False)
        engine.tick()
        assert len(calls) == 1
    finally:
        manager.unload()
        reset_hermes_home_override(token)
