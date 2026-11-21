"""The desk: what each role row tells the agent and the owner.

Organised by behaviour, not by the release that added it. The row format (separators, field
order, the "- role" prefix) is known in one place, `rows()`; the tests assert field values.
"""
from collections import namedtuple

import pytest

from cadence.desk import render_desk
from test_engine import KEY, arm, end, engine, pending, start

Row = namedtuple('Row', 'title rhythm last due today')


def desk(e):
    return render_desk(e.store, e.store.get_session(KEY), clock=e.clock,
                       timezone=e.policy.resolved_timezone(), policy=e.policy)


def rows(e):
    """Role rows keyed by wake id. The only place that knows how a row is laid out."""
    found = {}
    for line in desk(e).splitlines():
        if not line.startswith('- role '):
            continue
        head, rhythm, last, *due, today = line[len('- role '):].split(' · ')
        wake_id, _, title = head.partition(' ')
        assert last.startswith('last: ') and today.startswith('today '), line
        found[wake_id] = Row(title, rhythm, last[len('last: '):], ' · '.join(due), today[len('today '):])
    return found


def role(e, kind='every', trigger=None, **changes):
    return arm(e, kind, role=True, title=changes.pop('title', 'Notes'),
               trigger_json={'kind': kind, 'every': '2m'} if trigger is None else trigger, **changes)


def run_once(e, wake, summary='same'):
    e.dispatch(pending(e, wake))
    start(e)
    end(e, 'progress', False, summary=summary)


@pytest.mark.parametrize('kind,trigger,rhythm', [
    ('every', {'kind': 'every', 'every': '2m'}, 'every 2m'),
    ('every', {'kind': 'every', 'every': '1d', 'at': '09:00'}, 'every 1d at 09:00'),
    ('cron', {'kind': 'cron', 'cron': '0 3 * * *'}, 'cron `0 3 * * *`'),
    ('cron', {'kind': 'cron', 'cron': '30 9 1,15 * mon-fri'}, 'cron `30 9 1,15 * mon-fri`'),
    ('self', {'kind': 'self'}, 'self-paced'),
    # Stored triggers the renderer did not write itself must not break the desk.
    ('every', ['every', '2m'], 'every'),
    ('every', {'kind': 'every', 'every': '2m' + ' ' * 1900}, 'every 2m'),
], ids=['every', 'every-at', 'cron', 'cron-lists', 'self', 'trigger-not-a-dict', 'padded'])
def test_role_row_shows_the_rhythm_the_owner_set(engine, kind, trigger, rhythm):
    wake = role(engine, kind, trigger)
    assert rows(engine)[wake.id].rhythm == rhythm


def test_role_that_spent_todays_budget_rests_until_tomorrow(engine):
    wake = role(engine, budget_turns_per_day=1)
    before = rows(engine)[wake.id]
    assert before.due.startswith('next ') and before.today == '0/1'
    run_once(engine, wake)
    after = rows(engine)[wake.id]
    assert after.due == 'resting until tomorrow' and after.today == '1/1'
    assert after.rhythm == 'every 2m'


def test_only_a_cron_rhythm_is_a_code_span(engine):
    """Chat markdown pairs backticks across lines, so a stray one anywhere on the desk would swallow
    a cron expression's code span and let its asterisks render as bold."""
    e = engine
    crons = [role(e, 'cron', {'kind': 'cron', 'cron': '0 10 * * 1,4'}, title='Posts'),
             role(e, 'cron', {'kind': 'cron', 'cron': '*/5 * `x` * *'}, title='Ship `beta notes')]
    odd = role(e, trigger={'kind': 'every', 'every': '2`h', 'at': '09:`00'}, title='Odd')
    summarised = role(e, budget_turns_per_day=3)
    run_once(e, summarised, summary='updated `RELEASE-NOTES.md')
    paused = role(e, title='Paused', status='paused', status_reason='owner `asked')
    found = rows(e)
    assert desk(e).count('`') == 2 * len(crons)
    assert found[crons[0].id].rhythm == 'cron `0 10 * * 1,4`'
    assert found[crons[1].id].rhythm == 'cron `*/5 * x * *`'
    # Free text keeps its meaning with the backtick made an apostrophe, wherever it appears.
    assert found[crons[1].id].title == "Ship 'beta notes"
    assert found[odd.id].rhythm == "every 2'h at 09:'00"
    assert found[summarised.id].last == "updated 'RELEASE-NOTES.md"
    assert found[paused.id].due == "paused · owner 'asked"
