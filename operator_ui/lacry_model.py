"""Shared Sonnet configuration for Lacry and its existing analysis paths."""
import os

DEFAULT_MODEL = 'claude-sonnet-5-5'


def configured_model():
    return os.environ.get('LACRY_MODEL', '').strip() or DEFAULT_MODEL


def request_options(model, max_tokens=None):
    if model == DEFAULT_MODEL:
        return dict(model=model, max_tokens=max_tokens or 8192,
                    thinking=dict(type='adaptive'), output_config=dict(effort='medium'))
    return dict(model=model, max_tokens=max_tokens or 1000, temperature=0)
