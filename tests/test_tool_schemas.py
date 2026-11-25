import pytest

from conftest import FakeCtx
from cadence.registration import _register_surfaces
from schema_contracts import assert_action_schema


@pytest.mark.parametrize('name', ['responsibility', 'trigger'])
def test_registered_action_schema(name):
    ctx = FakeCtx()
    _register_surfaces(ctx, None)
    assert_action_schema(name, ctx.tools[name]['schema']['parameters'])
