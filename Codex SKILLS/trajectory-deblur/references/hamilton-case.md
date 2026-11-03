# Hamilton case — 2026-10-16

Project: `C:/Users/Cephla/Downloads/Bioyond_Cephla/Bioyond_Cephla` (locate its current checkout if moved).

Read `operator_ui/reports/trajectory_smoothing/Observations.md` for current evidence. Source is `operator_ui/demonstrations/return_home_20261016_130748/return_path.json`; trials are in `operator_ui/demonstrations/return_path_trials_20261016_131713/`. The observed sequence was:

- Group dense commands: 543 to 132; successful forward run 150.33 s total.
- Remove two transit loops, saving about 750 mm; 78-point reverse run 99.57 s total.
- Coalesce near-vertical segments: 75-point candidate prepared, not hardware-tested at that stage.
- Replace transit bends with lift/transfer/descent. Z253.8 trial failed with axis-3 collision; do not infer the collision cause from this report alone.
- Operator lowered arm and confirmed changed clearance. Z212 three-command forward run completed in 34.09 s at speed 40. Operator liked it but reported a slight backward entrance motion.
- Next requested experiment: 3 mm forward toward Hamilton during entry, preserving taught endpoint by placing the descent start 3 mm short. Read later observations for the outcome and acceptance; do not assume success from preparation.

Totals above include different preparation times and directions. They demonstrate iterative refinement, not a controlled proof that point reduction alone caused speed or smoothness gains. Original Home and the demonstrated Home-area are different coordinates.

Runtime: Flask singleton on localhost:5002; `recorded_return.py` owns reviewed replay authorization and start matching; `trajectory_queue.py` validates/transmits/monitors; `straight_transfer.py` validates specific route shapes; Lua source in `operator_ui/lua`. Read these before changing execution. Use `/state` and `/seq` for status. Never open a second controller connection. Existing trial exporter: `operator_ui/export_return_trial.py <recording-folder>`; export before another run/reload. Continuous recording is a session fact to recheck, not a permanent assumption.

The shape-specific route exceptions in this case are not permission to remove global limits for future paths. Candidate files are immutable; separate one-run permission records are consumed on attempt. Tests use fake hardware with the real Lua queue.

Related prior work: [Learning Preferences for Manipulation Tasks from Online Coactive Feedback](https://arxiv.org/abs/1601.00741) studies iterative improvement from user feedback. “Trajectory deblur” is the user's useful workflow name; novelty is not established, and this implementation currently uses explicit edits and saved evidence rather than a trained preference model.
