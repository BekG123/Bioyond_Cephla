"""Windows-safe run logging; retries file replacement only, never robot work."""
import math
from squid_bridge.state_io import atomic_write_json


def _json_value(value):
    # Preserve invalid feedback as explicit evidence without changing the live
    # state used by motion checks or making the failure log unserializable.
    if isinstance(value,float) and not math.isfinite(value):
        return {'invalid_numeric_feedback':repr(value)}
    if isinstance(value,dict):return {key:_json_value(item) for key,item in value.items()}
    if isinstance(value,(list,tuple)):return [_json_value(item) for item in value]
    return value


def write_run_record(path,record):
    atomic_write_json(path,_json_value(record))
