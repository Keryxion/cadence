"""Optional real Converse countdown contract without device I/O."""
import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest


def test_real_converse_countdown_uses_only_target_device(tmp_path, monkeypatch):
    root = os.environ.get('CADENCE_CONVERSE_ROOT')
    if not root: pytest.skip('Set CADENCE_CONVERSE_ROOT to test optional real Converse source')
    root = Path(root)
    import importlib.util
    package = '_cadence_converse_contract'
    spec = importlib.util.spec_from_file_location(package, root/'__init__.py', submodule_search_locations=[str(root)])
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, package, module)
    spec.loader.exec_module(module)
    cd = importlib.import_module(package+'.countdowns')
    from gateway.session_context import set_session_vars, clear_session_vars
    frames = []
    attachment = NS(send=frames.append)
    hub = NS(attachment=lambda key: attachment if key=='kitchen-device' else None)
    countdowns = cd.Countdowns(hub)
    monkeypatch.setattr(countdowns, '_schedule', lambda *args:None)
    tokens = set_session_vars(platform='converse',chat_id='kitchen-device',chat_type='dm',
                              session_key='kitchen',session_id='kitchen-sid')
    try:
        result = json.loads(countdowns.handle({'action':'set','in_seconds':300,'label':'Kitchen timer'}))
        assert result['result']=='set'
        assert len(frames)==1 and frames[0]['type']=='countdown'
        assert frames[0]['countdown_id']==result['countdown_id']
        assert list(countdowns._devices)==['kitchen-device']
        assert len(json.loads(countdowns.handle({'action':'list'}))['countdowns'])==1
    finally: clear_session_vars(tokens)
