"""Real loader/pulse compatibility and fail-closed requests; no gateway/device I/O."""
import inspect
import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_real_request_loader_provenance_and_normal_streaming(tmp_path, monkeypatch, clock):
    try:
        from hermes_cli.plugins import PluginManager
        from hermes_cli.plugins_manifest import parse_manifest_file
        from hermes_constants import set_hermes_home_override, reset_hermes_home_override
        from gateway.session_context import set_session_vars, clear_session_vars
    except ImportError as exc:
        if os.environ.get('CADENCE_REQUIRE_HERMES') == '1': pytest.fail(str(exc))
        pytest.skip('Hermes is not importable: '+str(exc))
    home = tmp_path/'home'
    home.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('HERMES_DISABLE_LAZY_INSTALLS','1')
    plugin = home/'plugins/cadence'
    shutil.copytree(ROOT, plugin, ignore=shutil.ignore_patterns('.git','.venv','.pytest_cache','__pycache__'))
    settings = {}
    import yaml
    (home/'config.yaml').write_text(yaml.safe_dump({'plugins':{'entries':{'cadence':{
        'enabled':True,'allow_gateway_injection':True,'settings':settings}}}}))
    token = set_hermes_home_override(home)
    manager = PluginManager(scope_key=str(home))
    try:
        manifest = parse_manifest_file(plugin/'plugin.yaml', plugin, 'user', '')
        manager._load_plugin(manifest)
        loaded = manager._plugins['cadence']
        assert loaded.enabled, loaded.error
        registration = sys.modules[loaded.module.__name__+'.cadence.registration']
        runtime = registration._RUNTIMES[manager.scope_key]
        runtime._stop.set()
        runtime._wake.set()
        runtime._thread.join(timeout=2)
        runtime.clock = clock
        runtime.restart = lambda: None
        injected = []
        host = NS(_served_profile_for_home=lambda path:'default' if Path(path)==home else None,
                  config=NS(multiplex_profiles=False))
        manager.set_gateway_message_injector(host, lambda **kw: injected.append(kw) or True)
        e = runtime.get_engine()
        e.paused = lambda:False
        from cadence.model import Session
        for key in ('mac','kitchen'):
            e.store.upsert_session(Session(key,'telegram','dm',key,key+'-sid'))
        requests = runtime.get_requests()
        # Requests need no host provenance. Bind the turn event only where this
        # Hermes accepts it, so the same round trip runs on every pinned version.
        parameters = inspect.signature(set_session_vars).parameters
        import gateway.session_context as session_context
        actor_context = ('actor_id' in parameters and 'turn_event' in parameters and
                         hasattr(session_context, '_SESSION_TURN_EVENT'))
        holds_stream = getattr(manager, 'holds_stream', lambda: False)
        assert not holds_stream(), 'Cadence must not globally buffer ordinary replies'

        def turn(event):
            return {'turn_event': event} if actor_context else {}

        def bind(key):
            options = dict(platform='telegram', chat_id=key, chat_type='dm',
                           session_key=key, session_id=key+'-sid')
            if actor_context:
                options.update(actor_id='mac-user', turn_event=None)
            return set_session_vars(**options)

        for key, name in [('mac', 'MacBook'), ('kitchen', 'Kitchen')]:
            tokens = bind(key)
            try:
                assert json.loads(runtime.request({'action':'rename','name':name}, session_id=key+'-sid'))['ok']
            finally:
                clear_session_vars(tokens)
        tokens = bind('mac')
        try:
            requests.hook('pre_llm_call', session_id='mac-sid', turn_id='human-turn', user_message='Ask Kitchen')
            result = json.loads(runtime.request({'action':'ask','to':'Kitchen','note':'Set a five minute countdown.'}, session_id='mac-sid'))
            assert result['ok'], result
            pulse = json.loads(runtime.tool({'action':'list'}, session_id='mac-sid'))
            assert 'error' not in pulse, pulse
        finally:
            clear_session_vars(tokens)
        assert len(injected) == 1
        text = injected[0]['content']
        event = NS(internal=True, text=text, metadata={'hermes_plugin_injection':True,
            'hermes_plugin_id':'cadence', 'gateway_session_key':'kitchen'})
        tokens = set_session_vars(platform='telegram', chat_id='kitchen', chat_type='dm',
            session_key='kitchen', session_id='kitchen-sid', **turn(event))
        try:
            context = requests.hook('pre_llm_call', session_id='kitchen-sid',
                turn_id='target-turn', user_message=text)
            assert 'YOUR OWN tools' in context['context']
            assert requests.hook('pre_tool_call', session_id='kitchen-sid',
                turn_id='target-turn', tool_name='terminal') is None
            # Actual Converse countdown implementation; injected attachment, no sockets or scheduler.
            root = os.environ.get('CADENCE_CONVERSE_ROOT')
            if root:
                import importlib.util
                package = '_cadence_request_countdown'
                spec = importlib.util.spec_from_file_location(package, Path(root)/'__init__.py',
                    submodule_search_locations=[root])
                module = importlib.util.module_from_spec(spec)
                monkeypatch.setitem(sys.modules, package, module)
                spec.loader.exec_module(module)
                cd = __import__(package+'.countdowns', fromlist=['Countdowns'])
                frames = []
                countdown = cd.Countdowns(NS(attachment=lambda key:NS(send=frames.append) if key=='kitchen' else None))
                monkeypatch.setattr(countdown, '_schedule', lambda *args:None)
                clear_session_vars(tokens)
                tokens = set_session_vars(platform='converse', chat_id='kitchen', chat_type='dm',
                    session_key='kitchen', session_id='kitchen-sid', **turn(event))
                timer = json.loads(countdown.handle({'action':'set','in_seconds':300,'label':'Kitchen'}))
                assert timer['result'] == 'set' and len(frames) == 1
            answer = json.loads(runtime.request({'action':'answer','id':result['request'],
                'outcome':'accepted','summary':'Countdown set in Kitchen.','notify':False}, session_id='kitchen-sid'))
            assert answer['ok'], answer
        finally:
            clear_session_vars(tokens)
        assert len(injected) == 2 and injected[-1]['session_key'] == 'mac'
        text = injected[-1]['content']
        event = NS(internal=True, text=text, metadata={'hermes_plugin_injection':True,
            'hermes_plugin_id':'cadence', 'gateway_session_key':'mac'})
        tokens = set_session_vars(platform='telegram', chat_id='mac', chat_type='dm',
            session_key='mac', session_id='mac-sid', **turn(event))
        try:
            context = requests.hook('pre_llm_call', session_id='mac-sid', turn_id='answer-turn', user_message=text)
            assert 'accepted' in context['context'] and 'Confirm success only for accepted' in context['context']
        finally:
            clear_session_vars(tokens)
        # When available, exercise the actual direct callback mixin without a hold.
        try:
            from agent.stream_delivery import StreamDeliveryMixin
        except ImportError:
            return  # Older pinned host without the direct callback mixin.
        stream = StreamDeliveryMixin()
        spoken = []
        stream._hold_stream = holds_stream()
        stream.stream_delta_callback = spoken.append
        stream._stream_callback = None
        stream._deliver_to_stream_callbacks('Ordinary streamed reply')
        assert spoken == ['Ordinary streamed reply']
    finally:
        for loaded in list(manager._plugins.values()):
            module=getattr(loaded,'module',None)
            registration=sys.modules.get(getattr(module,'__name__','')+'.cadence.registration')
            if registration:
                for runtime in list(registration._RUNTIMES.values()): runtime.close()
        reset_hermes_home_override(token)
