# Misc

Legacy standalone utilities that are not part of the accepted 48-well/Squid workflow. This folder is not an execution queue; archived robot scripts retain their original behavior and are not newly validated by relocation.

## ArUco utilities

`aruco/` contains the standalone `grab_aruco.py` grabber, `home_to_aruco.py` and its path JSON, `center_marker_step.py`, and printable marker images. Run scripts from the repository root using their new paths. The Home-to-marker script defaults to a no-network dry run.

Shared modules remain in `grab_skill/` and `operator_ui/`: Flask still imports `aruco.py`, camera calibration uses the ArUco model/anchors, and disk calibration uses shared geometry. They are dependencies, even though the accepted 48-well workflow does not use marker detection. `sequences_original.py` also remains because the classic disk endpoint and tests still import it.

Historical experiment records retain their original paths. Before archiving more code, check app imports, CLI callers, tests, relative data paths and evidence hashes. Do not relocate accepted evidence or shared calibration data based only on age or filename.
