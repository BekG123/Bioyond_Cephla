"""Shared host check for completed native loading; ordinary arrival checks stay strict."""
from researcher_teaching import TeachingError
from squid_bridge.loading_state import near_loading


def at_loading(actual,expected,bridge,serial=None):
    loading=bridge.get('loading',{})
    if loading.get('version')!=2:
        from squid_execution import at_position
        at_position(actual,expected)
        return  # Compatibility with earlier commissioned bridges at their exact reference.
    receipt=loading.get('receipt') or {}
    if (bridge.get('stage_simulated') is not False or not bridge.get('controller_serial')
            or (serial is not None and bridge['controller_serial']!=serial)
            or loading.get('status')!='completed' or loading.get('at_dropoff') is not True
            or receipt.get('session_id')!=loading.get('session_id')
            or receipt.get('controller_serial')!=bridge['controller_serial']
            or receipt.get('reference_hash')!=bridge.get('reference_hash')
            or not near_loading(actual,expected) or not near_loading(actual,loading.get('position',{}))):
        raise TeachingError('Squid has no current successful loading completion, or moved afterward. Use Squid’s Load position and wait for it to finish.')
    return loading
