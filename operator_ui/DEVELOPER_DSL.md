# Developer console and DSL inspector

Open `/developer`. The main console keeps connection controls, jogging,
gripper controls, camera and logs. 3D View remains a top-level tab. API
settings, workspace limits and older tools are expandable sections.

The visible **Calibration** panel has separate **Calibrate two-disk plate**
and **Calibrate 48-well plate** buttons. These calibrate only; they do not grip.
The two-disk button retains its original implementation. The 48-well button
uses the reviewed observation route and saved height reference with well-grid
detection. It requires saved Home, empty jaws and the unchanged plate setup.

Researcher **Full Calibration** now runs the 48-well sequence: calibration,
alignment, accepted descent, 3.9 mm grip, slow 5 mm lift and the existing Home
return. The complete route requires confirmation. Changed plate placement,
stale observations, changed reference evidence or failed stages stop the run;
the system does not adapt the taught endpoint automatically. This integration
has offline tests; physical verification remains an operator-supervised run.

## Inspect a failure

Open **Debugger**. Failed sequences captured after the updated
backend starts show their error, source location and Python excerpt when
available. The latest failure survives a restart. Historical failures without
source evidence are explicitly identified; the inspector does not guess a location.

The source explanation is a readable projection, not executable equivalence.
Unsupported Python constructs are marked `REVIEW`. **Explain with agent**
optionally sends the displayed evidence to the configured model. Its explanation
is unreviewed and has no hardware tools. Request failures outside the sequence
runner are not currently captured by this inspector.

## Write intended behavior

Load the parking example or write a draft using four-space indentation and no
semicolons. DSL v1 supports a machine declaration, a periodic check, `count`,
`check.logs`, independent `IF` blocks, Boolean conditions and these decisions:

- `WAIT`
- `PAUSE = human.review`
- `ASK = Role TYPE.Researcher(request=unload)`

Predicates are `Machine.has_fault`, `Machine.parked`, `no.tips` and
`Machine.door_closed`. `&`, `OR` and `!` express Boolean logic. Conditions may
compare `count` with a nonnegative integer. The first matching decision ends
the check. ASK and PAUSE suspend workflow progression; neither is a physical
emergency stop. The count is a check budget, not an elapsed-time guarantee.

**Translate and retranslate** generates a Python decision-function preview,
then reconstructs DSL from that generated Python. Translation is deterministic
and uses no model credits. Drafts remain in browser storage. The trailing
`agent(MODEL).translate()` and `agent(MODEL).retranslate()` lines are accepted
workflow notation, not runtime model invocations.

## Implementation boundary

No generated code is executed, deployed or connected to hardware. A future
runtime must supply fresh structured observations, persist the count, schedule
checks and suspend on ASK/PAUSE. `check.logs` does not parse arbitrary log text.
General Python cannot be translated losslessly into this small language.

The implementation lives in `developer_dsl.py`, `developer_diagnostics.py` and
`static/developer_console.{js,css}`. Sequence failures attach source evidence
without changing their original outcome. The existing researcher workflows
and motion implementations remain in place.

Run the offline unit suite with:

```powershell
.venv-realsense/Scripts/python.exe -B -m unittest discover -s operator_ui/tests -p test_developer_dsl.py
```

`operator_ui/tests/check_developer_browser.py` checks the actual static UI with
fake APIs in headless Edge. It does not connect to lab hardware.

## Ask Devin through the CLI

The Devin panel submits the displayed failure and optional DSL guidance to
the locally authenticated Devin CLI. No REST API key is needed. The default
Windows installation is discovered automatically; alternatively set
`CEPHLA_DEVIN_EXE` to the absolute executable path before starting Flask.

Jobs run in `%LOCALAPPDATA%\Cephla\DevinReview`, outside the repository. Devin
must trust that directory: if the output reports a trust error, open Devin
interactively in that folder and review its trust prompt, then exit. The
backend preserves workspace-trust checks. The Flask process must use the
Windows account that logged into Devin.

**Review** requests a text proposal. **Repair & push** starts a Devin Cloud job
on a dedicated `lacry/repair/<id>` branch from the current Git HEAD. The job is
instructed to reproduce the failure offline, preserve hardware limits, run
regression tests, then commit and push only its branch if checks pass. Main is
not merged and the lab checkout is not deployed or changed. Tests are
Devin-reported; the backend independently checks the remote branch commit.
Missing or inconsistent evidence is shown as `cloud_unknown`, not success.

**Auto-repair new failures** persists across restarts and sends new Runner
failures and Home request failures without requiring DSL. It does not backfill
old failures on enable. If another job is running, the failure is marked
deferred for manual submission; it is not silently retried. A failure ID gets
at most one repair attempt. Protected motion refusals may correctly result in
`needs_review` instead of a patch. No robot action is retried by this feature.

The panel polls background status. All submissions consume Devin usage. Local
reviews have a three-minute timeout; cloud jobs have a fifteen-minute CLI wait
limit. Closing or timing out the CLI does not cancel a cloud session. An
uncertain cloud outcome blocks further submissions until inspected. Only the latest
job is retained in `latest.json`; prompt/output temporary files are removed
after completion. A restart marks an unfinished record as interrupted and does
not resume it. Review the earlier CLI session before resubmitting.

The separate CLI configuration denies local tool-based file reads, edits,
execution and MCP calls, disables local subagents and imported settings, and
retains normal permission mode. Cloud jobs use their remote VM and GitHub
connection; Local Hands is not approved. This is not a local OS sandbox.
No generated response is executed or applied by Flask. Review snippets for sensitive content before
submitting; token-pattern redaction is best effort, not a complete secret scan.

References: [Devin permissions](https://docs.devin.ai/cli/reference/permissions)
and [configuration](https://docs.devin.ai/cli/reference/configuration/config-file).
