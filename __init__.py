"""Hermes loader entry point. Importing this file does no registration work."""


def register(ctx):
    from .cadence.registration import register as register_plugin
    return register_plugin(ctx)
