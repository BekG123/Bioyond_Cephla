# Developer console and DSL inspector

Open `/developer`. The main console keeps connection controls, jogging,
gripper controls, camera and logs. 3D View remains a top-level tab. API
settings, workspace limits and older tools are expandable sections.

## Inspect a failure

Open **Bug inspector · DSL**. Failed sequences captured after the updated
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
