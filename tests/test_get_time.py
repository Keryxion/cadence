from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
import sys

import pytest

from cadence.get_time import handle


@pytest.mark.parametrize(('utc', 'local'), [
    ('2026-11-22T09:54:49Z', '2026-11-22T04:54:49-05:00'),
    ('2026-07-01T12:00:00Z', '2026-07-01T08:00:00-04:00'),
    ('2026-03-08T06:59:59Z', '2026-03-08T01:59:59-05:00'),
    ('2026-03-08T07:00:00Z', '2026-03-08T03:00:00-04:00'),
    ('2026-11-01T05:30:00Z', '2026-11-01T01:30:00-04:00'),
    ('2026-11-01T06:30:00Z', '2026-11-01T01:30:00-05:00'),
])
def test_explicit_zone_reads_one_instant(utc, local, monkeypatch):
    monkeypatch.setitem(sys.modules, 'hermes_time', SimpleNamespace(get_timezone_name=lambda: 'Asia/Tokyo'))
    clock = Mock()
    clock.now.return_value = datetime.fromisoformat(utc.replace('Z', '+00:00')).timestamp() + 0.25
    assert handle({'timezone':'America/New_York'}, clock) == {
        'utc':utc, 'local':local, 'timezone':'America/New_York'}
    clock.now.assert_called_once_with()


@pytest.mark.parametrize(('setting','zone'), [('', 'UTC'), ('Asia/Tokyo','Asia/Tokyo')])
def test_profile_timezone_default(setting, zone, monkeypatch, clock):
    monkeypatch.setitem(sys.modules, 'hermes_time', SimpleNamespace(get_timezone_name=lambda: setting))
    report = handle({}, clock)
    assert report['timezone'] == zone
    assert datetime.fromisoformat(report['utc'].replace('Z','+00:00')) == datetime.fromisoformat(report['local'])


@pytest.mark.parametrize('args', [{}, {'timezone':'EST'}, {'timezone':'localtime'}, {'timezone':None},
                                  {'timezone':'Does/Not_Exist'}])
def test_invalid_timezone(args, monkeypatch, clock):
    monkeypatch.setitem(sys.modules, 'hermes_time', SimpleNamespace(get_timezone_name=lambda: 'Bad/Default'))
    assert handle(args, clock)['error'] == 'invalid_timezone'
