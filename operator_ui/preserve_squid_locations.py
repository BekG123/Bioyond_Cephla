"""Import an operator-requested saved location snapshot. No hardware commands.

The prior selection must bind to the same configured controller/reference. Only
XY is imported; acquisition controls come from the currently open Squid tab.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from squid_adapter import SquidAdapter, native_command
from squid_execution import SquidExecution, digest, at_position
from squid_bridge.imaging_lifecycle import imaging_target


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('snapshot',type=Path)
    args=parser.parse_args()
    adapter=SquidAdapter(background=False)
    adapter.connect()
    engine=SquidExecution(adapter)
    state=engine.ready(idle=True)
    configured=engine.profile()
    reference=native_command('get_stage_reference',{})
    previous=json.loads(engine.selection_path.read_text(encoding='utf-8'))
    old=previous['plan'];old_profile=old['profile']
    if (digest(configured)!=old['configured_hash'] or
            digest(old_profile)!=old['profile_hash'] or
            hashlib.sha256(old_profile['captured_yaml'].encode()).hexdigest()!=old_profile['params']['settings_sha256'] or
            reference['reference_hash']!=old_profile['loading_reference_hash'] or
            reference['controller_serial']!=configured['stage_controller_serial'] or
            state.get('stage_simulated') is not False):
        raise RuntimeError('Controller, configuration or original reference changed; no locations imported.')
    at_position(reference['dropoff'],configured['loading_position'])
    current=engine.current_controls()
    if current['summary']['fovs']:
        plan=engine.prepare(allow_loading_return=True)
        print(json.dumps(dict(source='live GUI',selected=plan['profile']['selected_settings'])))
        return
    snapshot_path=args.snapshot.resolve(strict=True)
    saved_text=snapshot_path.read_text(encoding='utf-8')
    merged=engine.current_with_saved_xy(saved_text,current)
    target=imaging_target(merged['yaml'],reference['scan_limits'])
    profile=deepcopy(configured)
    profile.update(command='run_acquisition_from_yaml',captured_yaml=merged['yaml'],
        params=dict(settings_sha256=merged['sha256']),selected_settings=merged['summary'],
        settings_capture_position=target,loading_reference_hash=reference['reference_hash'],
        scan_entry=target,imaging_lifecycle_version=reference['imaging_lifecycle_version'])
    plan=dict(profile=profile,profile_hash=digest(profile),configured_hash=digest(configured),
        session=state['session'],loading_position=configured['loading_position'],
        simulation=state['simulation'],stage_simulated=state['stage_simulated'])
    # Preserve the legacy tab's reference before replacing the compatibility cache.
    engine.location_event('capture',record=previous,record_sha256=digest(previous))
    engine.remember_selection(plan,source=dict(kind='operator_requested_saved_xy_import',
        path=str(snapshot_path),snapshot_sha256=hashlib.sha256(saved_text.encode()).hexdigest(),
        original_file_modified_at=snapshot_path.stat().st_mtime,
        binding_reference_hash=reference['reference_hash'],
        notice='Saved XY reference, not an executed or successful imaging experiment.'))
    checked=engine.prepare(allow_loading_return=True)
    engine.verify(checked)
    print(json.dumps(dict(archive=str(engine.locations_path),selected=checked['profile']['selected_settings'],
        scan_entry=checked['profile']['scan_entry'],motion_started=False),indent=2))


if __name__=='__main__':main()
