import pytest

from cadence.registration import Runtime
from test_engine import GatewayCtx, KEY


def test_grouped_settings_refill_and_restart(tmp_path, clock):
    ctx = GatewayCtx(tmp_path, settings={'interruptions': {
        'capacity': 4, 'initial': 1, 'refill_per_hour': 2}})
    runtime = Runtime(ctx, clock=clock)
    try:
        engine = runtime.get_engine()
        assert engine.interruption_tokens(KEY) == 1
        engine.interruption_tokens(KEY, spend=True)
        clock.advance(1799)
        assert engine.interruption_tokens(KEY) == 0
        clock.advance(1)
        assert engine.interruption_tokens(KEY) == 1
        clock.advance(18000)
        assert engine.interruption_tokens(KEY) == 4
    finally:
        runtime.close()
    restarted = Runtime(ctx, clock=clock)
    try:
        assert restarted.get_engine().interruption_tokens(KEY) == 4
    finally:
        restarted.close()


@pytest.mark.parametrize('rate', [0, -1, True, 'bad', float('inf'), float('nan')])
def test_invalid_refill_reports_settings_error(tmp_path, clock, rate):
    runtime = Runtime(GatewayCtx(tmp_path, settings={
        'interruptions': {'refill_per_hour': rate}}), clock=clock)
    try:
        assert runtime.policy().interruption_refill_seconds == 300
        assert runtime.settings_error
    finally:
        runtime.close()


def test_initial_balance_is_capped(tmp_path, clock):
    runtime = Runtime(GatewayCtx(tmp_path, settings={
        'interruptions': {'capacity': 2, 'initial': 10, 'refill_per_hour': 0.5}}), clock=clock)
    try:
        assert runtime.get_engine().interruption_tokens(KEY) == 2
        assert runtime.policy().interruption_refill_seconds == 7200
    finally:
        runtime.close()
