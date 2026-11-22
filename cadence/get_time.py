"""A read-only clock tool for the current Hermes profile."""
from .clock import format_timestamp, report_zone

SCHEMA = {
    'name': 'get_time',
    'description': 'Read the Hermes host clock in UTC and local time.',
    'parameters': {
        'type': 'object',
        'properties': {'timezone': {'type': 'string', 'description':
            'IANA timezone name. Defaults to the configured Hermes timezone, or UTC if unset.'}},
        'additionalProperties': False,
    },
}


def handle(args, clock):
    if not isinstance(args, dict) or set(args) - {'timezone'}:
        return {'error': 'invalid_arguments', 'detail': 'get_time accepts only the optional timezone field.'}
    if 'timezone' in args:
        name = args['timezone']
    else:
        from hermes_time import get_timezone_name
        name = get_timezone_name() or 'UTC'
    try:
        zone = report_zone(name)
    except ValueError as exc:
        return {'error': 'invalid_timezone', 'detail': str(exc)}
    instant = clock.now()
    return {'utc': format_timestamp(instant), 'local': format_timestamp(instant, zone), 'timezone': zone.key}
