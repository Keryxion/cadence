"""Shared assertions for registered and provider-normalized parameter schemas."""
import pytest
from jsonschema import Draft202012Validator, ValidationError


def assert_action_schema(name, parameters):
    Draft202012Validator.check_schema(parameters)
    validator = Draft202012Validator(parameters)
    assert parameters['required'] == ['action']
    assert parameters['additionalProperties'] is False
    actions = parameters['properties']['action']['enum']
    valid = [dict(action=action, id='item') for action in ('get', 'pause', 'resume', 'delete')]
    valid += [{'action': 'list'}, {'action': 'list', 'detailed': True},
              {'action': 'update', 'id': 'item', 'title': 'Updated'}]
    if name == 'responsibility':
        valid += [{'action': 'create', 'title': 'Release', 'charter': 'Check readiness',
                   'checks': {'min_per_24h': 1, 'budget_per_24h': 30}},
                  {'action': 'finish', 'id': 'item', 'reason': 'Released'}]
    else:
        valid += [{'action': 'create', 'responsibility_id': 'item', 'when': {'kind': 'startup'}},
                  {'action': 'create', 'title': 'Reminder', 'note': 'Check readiness',
                   'when': {'kind': 'at', 'at': 'tomorrow 09:00'}}]
    assert set(actions) == {call['action'] for call in valid}
    for call in valid:
        validator.validate(call)
    invalid = [{}, {'actoin': 'list'}, {'action': 'unknown'}, {'action': 'get'},
               {'action': 'list', 'title': 'Wrong action'}, {'action': 'list', 'extra': 1},
               {'action': 'update', 'id': 'item'}]
    invalid += [dict(action=action) for action in ('pause', 'resume', 'delete')]
    if name == 'responsibility':
        invalid += [{'action': 'create', 'title': 'Missing charter and checks'},
                    {'action': 'finish', 'id': 'item'}]
    else:
        invalid += [{'action': 'create', 'responsibility_id': 'item'},
                    {'action': 'create', 'when': {'kind': 'startup'}},
                    {'action': 'create', 'responsibility_id': 'item', 'when': {'kind': 'at'}},
                    {'action': 'create', 'responsibility_id': 'item',
                     'when': {'kind': 'startup', 'typo': True}}]
    for call in invalid:
        with pytest.raises(ValidationError):
            validator.validate(call)
