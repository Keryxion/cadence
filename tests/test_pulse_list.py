from dataclasses import replace

import pytest
from cadence.model import Wake
from test_engine import KEY, arm, end, engine, pending, start


def test_short_list_hides_history_and_internal_fields(engine):
    e = engine
    arm(e, status='done', title='Old task')
    paused = arm(e, status='paused', status_reason='owner_paused', title='Paused task')
    role = arm(e, 'every', role=True, title='Build', next_due_at=e.clock.now()+1800)
    e.dispatch(pending(e, role))
    start(e)
    end(e, 'blocked', False, summary='Waiting for CI')
    result = e.tool.handle({'action':'list'}, session_id='sid')
    assert [w['id'] for w in result['wakes']] == [role.id, paused.id]
    row = result['wakes'][0]
    assert row['last_result']['summary'] == 'Waiting for CI'
    assert row['last_result']['outcome'] == 'blocked'
    assert row['next_check_at'] is not None
    assert not {'session_key','chat_id','tokens_in','trigger_json','scratch','cache'} & row.keys()
    detailed = e.tool.handle({'action':'list','detailed':True}, session_id='sid')
    assert len(detailed['wakes']) == 3
    assert all('session_key' in w and 'trigger_json' in w for w in detailed['wakes'])
    assert e.tool.handle({'action':'list','detailed':False}, session_id='sid') == result


def test_list_reports_held_watcher_and_excludes_other_chat(engine):
    e = engine
    watcher = arm(e, 'subagent_done', title='CI')
    e.store.create_wake(Wake('other', 'Private task', 'at'))
    e.policy = replace(e.policy, interruption_capacity=0)
    e.dispatch(pending(e, watcher))
    row, = e.tool.handle({'action':'list'}, session_id='sid')['wakes']
    assert row['reason'] == 'held_interruptions'
    assert 'last_result' not in row


@pytest.mark.parametrize('value', ['true', 1, None])
def test_list_rejects_nonboolean_detail_flag(engine, value):
    assert engine.tool.handle({'action':'list','detailed':value}, session_id='sid')['error'] == 'invalid_request'
