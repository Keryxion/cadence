"""Deployment tests never contact a host or restart a real service."""
import fcntl
import importlib.machinery
import sqlite3
import time
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40
OLD = 'b' * 40


@pytest.fixture
def host(tmp_path):
    home = tmp_path / 'home'
    plugin = home / '.hermes/plugins/cadence'
    (plugin / '.git').mkdir(parents=True)
    commands = tmp_path / 'bin'
    commands.mkdir()
    log = tmp_path / 'calls'
    mock = commands / 'mock'
    mock.write_text('''#!{python}
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as f: f.write(json.dumps([name, *args]) + '\\n')
if name == 'git':
    if args == ['rev-parse', 'HEAD']: print('{old}')
    elif args[:2] == ['status', '--porcelain']: print('dirty' if os.getenv('DIRTY') else '', end='')
    elif args[0] == 'show': print('python_dependencies: [changed]' if os.getenv('DEPS') and args[1].startswith('{sha}') else 'name: cadence')
    elif args[0] == 'checkout': pathlib.Path(os.environ['CURRENT']).write_text(args[-1])
    elif args[0] == 'fetch' and os.getenv('FETCH_FAIL'): sys.exit(1)
elif name == 'sudo':
    if args[-1] == '--value': print('123')
    elif os.getenv('RESTART_FAIL') and pathlib.Path(os.environ['CURRENT']).read_text() == '{sha}': sys.exit(1)
elif name == 'cadence-alpha-health':
    current = pathlib.Path(os.environ['CURRENT']).read_text()
    if os.getenv('HEALTH_FAIL') == 'all' or os.getenv('HEALTH_FAIL') == current: sys.exit(1)
    counter = pathlib.Path(os.environ['COUNTER'])
    n = int(counter.read_text()) + 1 if counter.exists() else 1
    counter.write_text(str(n))
    print(n)
'''.format(python=sys.executable, old=OLD, sha=SHA))
    mock.chmod(0o755)
    for name in ('git', 'sudo', 'flock', 'sleep', 'cadence-alpha-health'):
        (commands / name).symlink_to(mock)
    local = home / '.local/bin'
    local.mkdir(parents=True)
    (local / 'cadence-alpha-health').symlink_to(mock)
    env = dict(os.environ, HOME=str(home), HERMES_HOME=str(home / '.hermes'),
               PATH=f'{commands}:{os.environ["PATH"]}', CALLS=str(log),
               CURRENT=str(tmp_path / 'current'), COUNTER=str(tmp_path / 'counter'))
    Path(env['CURRENT']).write_text(OLD)

    def run(command=f'deploy {SHA}', **settings):
        result = subprocess.run(['bash', str(ROOT / 'deploy/cadence-alpha')],
                                env=dict(env, SSH_ORIGINAL_COMMAND=command, **settings),
                                capture_output=True, text=True)
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return result, calls
    return run


@pytest.mark.parametrize('command', ['', 'deploy abc', f'deploy {SHA} extra',
                                    f'deploy {SHA}\nwhoami', f'other {SHA}', f'deploy {"A" * 40}'])
def test_rejects_invalid_command_before_any_action(host, command):
    result, calls = host(command)
    assert result.returncode == 2
    assert calls == []


def test_success(host):
    result, calls = host()
    assert result.returncode == 0, result.stderr
    assert ['git', 'checkout', '-q', '--detach', SHA] in calls
    assert sum(c[0] == 'cadence-alpha-health' for c in calls) == 2
    assert sum('restart' in c for c in calls) == 1


@pytest.mark.parametrize('settings', [{'DIRTY': '1'}, {'DEPS': '1'}, {'FETCH_FAIL': '1'}])
def test_preflight_failure_does_not_restart_or_checkout(host, settings):
    result, calls = host(**settings)
    assert result.returncode != 0
    assert not any('restart' in c or 'checkout' in c for c in calls)


@pytest.mark.parametrize('settings', [{'HEALTH_FAIL': SHA}, {'RESTART_FAIL': '1'}, {'HEALTH_FAIL': 'all'}])
def test_failed_candidate_rolls_back_and_reports_failure(host, settings):
    result, calls = host(**settings)
    assert result.returncode == 1
    assert ['git', 'checkout', '-q', '--detach', OLD] in calls
    assert sum('restart' in c for c in calls) == 2
    if settings.get('HEALTH_FAIL') == 'all':
        assert 'rollback failed' in result.stderr


def test_same_sha_still_checks_health(host):
    result, calls = host(f'deploy {OLD}')
    assert result.returncode == 0
    assert any(c[0] == 'cadence-alpha-health' for c in calls)


@pytest.fixture
def health(tmp_path):
    loader = importlib.machinery.SourceFileLoader('alpha_health', str(ROOT / 'deploy/cadence-alpha-health'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    now = time.time()
    meta = dict(poller_pid=str(os.getpid()), epoch='test-epoch',
                poller_started_at=str(now - 5), last_tick_at=str(now - 1))

    def check(**updates):
        values = dict(meta, **updates)
        with sqlite3.connect(tmp_path / 'cadence.db') as db:
            db.execute('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)')
            db.executemany('INSERT OR REPLACE INTO meta VALUES (?, ?)', values.items())
        return module.sample(tmp_path, os.getpid(), now - 10, now)
    with (tmp_path / 'poller.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield check


def test_health_reads_existing_gateway_poller(health):
    assert health().startswith('test-epoch:')


@pytest.mark.parametrize('updates', [
    {'poller_pid': '0'}, {'epoch': ''}, {'last_tick_at': '0'},
    {'last_tick_at': 'nan'}, {'last_tick_at': 'inf'},
    {'poller_started_at': '0'}, {'last_error': 'ValueError'},
    {'settings_error': 'bad'}, {'probing_since': '1'},
])
def test_health_rejects_invalid_evidence(health, updates):
    with pytest.raises(ValueError):
        health(**updates)


def test_health_requires_lock_owner(tmp_path):
    loader = importlib.machinery.SourceFileLoader('alpha_health_unlocked', str(ROOT / 'deploy/cadence-alpha-health'))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    now = time.time()
    with sqlite3.connect(tmp_path / 'cadence.db') as db:
        db.execute('CREATE TABLE meta (key TEXT, value TEXT)')
        db.executemany('INSERT INTO meta VALUES (?, ?)', dict(
            poller_pid=str(os.getpid()), epoch='e', poller_started_at=str(now-2),
            last_tick_at=str(now-1)).items())
    (tmp_path / 'poller.lock').touch()
    with pytest.raises(ValueError, match='lock owner'):
        module.sample(tmp_path, os.getpid(), now-10, now)


@pytest.mark.parametrize(('action', 'added', 'labels', 'targets'), [
    ('labeled', 'alpha:sakura', [], ['sakura']),
    ('labeled', 'other', ['alpha:penny'], []),
    ('synchronize', '', ['alpha:penny', 'other', 'alpha:hermie'], ['penny', 'hermie']),
    ('reopened', '', ['alpha:sakura'], ['sakura']),
])
def test_workflow_payload(tmp_path, action, added, labels, targets):
    workflow = yaml.safe_load((ROOT / '.github/workflows/alpha.yml').read_text())
    script = workflow['jobs']['deploy']['steps'][0]['run']
    mock = tmp_path / 'gh'
    mock.write_text(f'#!{sys.executable}\nimport os, sys\nwith open(os.environ["PAYLOADS"], "a") as f: f.write(sys.stdin.read().replace("\\n", " ") + "\\n")\n')
    mock.chmod(0o755)
    output = tmp_path / 'payloads'
    result = subprocess.run(['bash', '-e', '-c', script], capture_output=True, text=True,
                            env=dict(os.environ, PATH=f'{tmp_path}:{os.environ["PATH"]}',
                                     ACTION=action, ADDED=added, LABELS=json.dumps(labels),
                                     SHA=SHA, PR='42', GH_REPO='Keryxion/cadence', PAYLOADS=str(output)))
    assert result.returncode == 0, result.stderr
    payloads = [json.loads(line) for line in output.read_text().splitlines()] if output.exists() else []
    assert [p['environment'] for p in payloads] == targets
    for payload in payloads:
        assert payload['ref'] == SHA
        assert payload['required_contexts'] == []
        assert payload['auto_merge'] is False
        assert payload['production_environment'] is False
        assert payload['transient_environment'] is True


def test_workflow_trust_boundary():
    workflow = yaml.safe_load((ROOT / '.github/workflows/alpha.yml').read_text())
    assert workflow.get('on', workflow.get(True)) == {'pull_request_target': {'types': ['labeled', 'synchronize', 'reopened']}}
    assert workflow['permissions'] == {'deployments': 'write'}
    job = workflow['jobs']['deploy']
    assert job['if'] == 'github.event.pull_request.head.repo.full_name == github.repository'
    assert not any('uses' in step for step in job['steps'])
    assert job['steps'][0]['env']['SHA'] == '${{ github.event.pull_request.head.sha }}'
    crow = yaml.safe_load((ROOT / '.crow/alpha.yaml').read_text())
    assert crow['skip_clone'] is True
    assert crow['when'] == [{'event': 'deployment', 'environment': ['sakura', 'penny', 'hermie']}]
