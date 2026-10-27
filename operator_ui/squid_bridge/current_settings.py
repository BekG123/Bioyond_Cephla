"""Read the active Squid acquisition tab on its Qt thread, without movement."""
from types import SimpleNamespace
from pathlib import Path
import hashlib
import tempfile
import threading

from qtpy.QtCore import QObject, Signal, Slot, Qt


class CurrentSettingsBridge(QObject):
    requested = Signal(object)

    def __init__(self, server):
        super().__init__()
        self.server = server
        self.moveToThread(server.gui.thread())
        self.requested.connect(self._capture, Qt.QueuedConnection)

    def capture(self):
        return self.invoke('capture', {})

    def controls(self):
        """Export live controls even when loading has cleared the XY selection."""
        return self.invoke('controls', {})

    def start(self, settings_sha256, experiment_id, base_path):
        return self.invoke('start', dict(settings_sha256=settings_sha256,
                           experiment_id=experiment_id, base_path=base_path))

    def abort(self, experiment_id):
        return self.invoke('abort', dict(experiment_id=experiment_id))

    def invoke(self, action, arguments):
        request = {"finished": threading.Event(), "cancelled": False,
                   "action": action, "arguments": arguments}
        self.requested.emit(request)
        if not request["finished"].wait(15):
            request["cancelled"] = True
            raise RuntimeError("Squid did not export its current settings in time.")
        if request.get("error"):
            raise RuntimeError(request["error"])
        return request["result"]

    @Slot(object)
    def _capture(self, request):
        try:
            if not request["cancelled"]:
                if request['action'] == 'start':
                    request['result'] = self.start_current(**request['arguments'])
                elif request['action'] == 'abort':
                    request['result'] = self.abort_current(**request['arguments'])
                else:
                    request['result'] = self.export(allow_empty=request['action'] == 'controls')
        except Exception as error:
            request["error"] = str(error)
        finally:
            request["finished"].set()

    def export(self, allow_empty=False):
        import yaml
        from control.core.multi_point_controller import _save_acquisition_yaml
        from control.core.multi_point_utils import ScanPositionInformation

        server = self.server
        controller = server.multipoint_controller
        if controller.acquisition_in_progress():
            raise RuntimeError("Wait for the current Squid acquisition to finish.")
        widget = server.gui.recordTabWidget.currentWidget()
        if not callable(getattr(widget, "configure_controller_from_ui", None)):
            raise RuntimeError("Select the imaging acquisition tab in Squid first.")
        if widget.checkbox_useFocusMap.isChecked():
            raise RuntimeError("The native settings export cannot reproduce a fitted focus map. "
                               "No experiment was started.")
        channels = widget.channel_sequence.ordered_selected_names()
        if not channels:
            raise RuntimeError("Select at least one imaging channel in Squid.")
        reason = widget.configure_controller_from_ui()
        if reason:
            raise RuntimeError(reason)
        coordinates = widget.scanCoordinates
        fovs = sum(len(v) for v in coordinates.region_fov_coordinates.values())
        if not fovs and not allow_empty:
            raise RuntimeError("Select the wells or imaging locations in Squid first.")
        # Qt controllers cannot be copied/pickled. Snapshot their Python data
        # into a plain object and call the read-only native parameter builder.
        # This also supplies metadata absent before the first acquisition,
        # without changing any live controller fields or starting acquisition.
        export_controller = SimpleNamespace(**vars(controller))
        export_controller.experiment_ID = "current_Squid_settings"
        export_controller.timestamp_acquisition_started = 0
        params = controller.build_params.__func__(
            export_controller, ScanPositionInformation.from_scan_coordinates(coordinates))
        if params.Nt < 1 or params.NZ < 1:
            raise RuntimeError("Automatic experiments require finite image and time-point counts.")
        if getattr(controller, "region_laser_af_offsets", {}):
            raise RuntimeError("Per-region focus offsets cannot yet be exported faithfully.")
        store = server.microscope.objective_store
        objective = dict(name=store.current_objective,
                         camera_binning=list(server.microscope.camera.get_binning()))
        with tempfile.TemporaryDirectory(prefix="lacry-settings-") as directory:
            _save_acquisition_yaml(params, directory,
                region_shapes=getattr(coordinates, "region_shapes", None),
                widget_type=controller.widget_type, objective_info=objective,
                wellplate_format=getattr(coordinates, "format", None),
                scan_size_mm=getattr(controller, "scan_size_mm", 0),
                overlap_percent=getattr(controller, "overlap_percent", 10))
            data = yaml.safe_load((Path(directory)/"acquisition.yaml").read_text(encoding="utf-8"))
        text = yaml.safe_dump(data, sort_keys=True)
        return dict(yaml=text, sha256=hashlib.sha256(text.encode()).hexdigest(),
                    summary=dict(channels=channels, fovs=fovs, nz=params.NZ, nt=params.Nt,
                                 total_images=fovs*len(channels)*params.NZ*params.Nt,
                                 objective=store.current_objective,
                                 widget_type=controller.widget_type))

    def start_current(self, settings_sha256, experiment_id, base_path):
        """Check and start on one Qt turn; never overwrite the researcher's selections."""
        import re
        if not re.fullmatch(r'Lacry_[a-f0-9]{32}', experiment_id):
            raise RuntimeError('A unique Lacry experiment identifier is required.')
        current = self.export()
        if current['sha256'] != settings_sha256:
            raise RuntimeError('Squid settings changed after confirmation. Request a new experiment.')
        controller = self.server.multipoint_controller
        widget = self.server.gui.recordTabWidget.currentWidget()
        controller.set_base_path(base_path)
        controller.start_new_experiment(experiment_id)
        widget.set_acquisition_running_state(True, controller.NZ, controller.deltaZ*1000)
        try:
            if not controller.run_acquisition():
                raise RuntimeError('Squid did not start the acquisition.')
        except Exception:
            widget.set_acquisition_running_state(False, controller.NZ, controller.deltaZ*1000)
            raise
        return dict(started=True, experiment_id=controller.experiment_ID,
                    settings_sha256=settings_sha256, **current['summary'])

    def abort_current(self, experiment_id):
        controller = self.server.multipoint_controller
        if controller.experiment_ID != experiment_id:
            raise RuntimeError('A different imaging job is active; it was not cancelled.')
        active = controller.acquisition_in_progress()
        if active:
            controller.request_abort_aquisition()
        return dict(abort_requested=active, experiment_id=experiment_id)


def install(server):
    if server.gui is None:
        return
    bridge = CurrentSettingsBridge(server)
    server._lacry_current_settings = bridge
    server._commands["get_current_acquisition_settings"] = bridge.capture
    server._commands["get_current_acquisition_controls"] = bridge.controls
    server._commands["run_current_acquisition"] = bridge.start
    server._commands["abort_current_acquisition"] = bridge.abort
