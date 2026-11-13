# Proposals for the owner

Nothing here has been applied. `machines/` and `CLAUDE.md` are unchanged.

## 1. Schema change: `manifest_schema.diff`

```
git apply labfacade/proposals/manifest_schema.diff
py machines/validate.py
```

It does two things:

- Accepts the fields already in `bioyond_s4.yaml` (`plate_session_workflow`, the four
  location keys, and the `holder_preparation_pending_supervised_trial` status). Until it
  is applied, `bioyond_s4.yaml` fails validation and the facade refuses every Bioyond
  operation.
- Lets a `human_gate` entry be either the current string or a typed object.

## 2. Typed gates

```yaml
human_gate:
  - {type: presence_attestation, text: at the E-stop}
  - {type: sensor_check, sensor: door_closed, text: door closed}
  - {type: fresh_confirmation, text: path clear}
```

| Type | Who answers | When |
| --- | --- | --- |
| `sensor_check` | the machine's sensor, through the backend | every step, automatically |
| `presence_attestation` | the person's run-level attestation and heartbeat | once per run |
| `fresh_confirmation` | a person, for this step | each time, expires in two minutes |

Strings keep working. The facade already reads "E-stop" as a presence attestation and
maps these phrases to sensors: `door closed`, `no object is held`, `no plate held`,
`destination empty`, `plate seated`, `plate loaded and supported`. Every other string is
a fresh confirmation, which is why typing the gates is what cuts the number of prompts.

## 3. Qualification keys

The facade looks up qualification by operation name. These motion or state-change
operations have no entry of that name today, so they are treated as `untested`:

- `hamilton.yaml`: `encoder_opening_test`
- `bioyond_s4.yaml`: `enable_robot`, `start_program`, `run_station_job`, `go_home`,
  `grip_by_torque`, `release`
- `squid.yaml`: `home_stage`, `abort_imaging`

Either add an entry under each operation's own name, or tell me the mapping you want
(for example `run_station_job` with `device_id: 12` and `action: place` → `squid_dropoff`).

`hamilton.yaml` also still marks the plate hand-off as `blocked` with zero round trips,
which the latest commits ("successful five-cycle Hamilton and Squid handling run")
appear to contradict.

## 4. Suggested wording for CLAUDE.md, safety rules

> A plan approved through the console authorizes exactly the steps and parameters it
> lists, until it expires or the plan changes. For supervised operations a person must
> also attest they are at the E-stop for the run and keep the heartbeat alive; if it
> lapses, the run pauses. Enabling, clearing errors and starting a controller program
> still need a fresh confirmation each time. An agent never grants, extends or imitates
> an approval, an attestation or a confirmation.
