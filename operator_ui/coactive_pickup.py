"""Developer-only, measured corrections to a context-bound pickup reference.

Online preference update: an accepted hand-demonstrated endpoint replaces the
previous endpoint for this reference. No model-weight training or robot writes.
"""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from uuid import uuid4

from imitation_agent import close_pose, digest
from researcher_teaching import TeachingError, numbers, utc_now


class CoactivePickup:
    def __init__(self, references, path, service, runner, invalidate):
        self.references, self.path = references, Path(path)
        self.service, self.runner, self.invalidate = service, runner, invalidate
        self.lock = threading.RLock()

    def _load(self):
        if not self.path.exists():
            return dict(schema='cephla.coactive-pickup.v1', accepted=None, proposals=[], preferences=[], outcomes=[])
        data = json.loads(self.path.read_text(encoding='utf-8'))
        if data.get('schema') != 'cephla.coactive-pickup.v1':
            raise TeachingError('Pickup learning history needs developer review.')
        return data

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        name = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=self.path.parent, delete=False) as f:
                name = f.name
                json.dump(data, f, indent=2, allow_nan=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def reference(self):
        base = self.references.load()
        with self.lock:
            accepted = self._load()['accepted']
        if not accepted or accepted['base_id'] != base['id']:
            return base
        ref = accepted['reference']
        if digest({k:v for k,v in ref.items() if k != 'id'}) != ref['id']:
            raise TeachingError('The learned reference changed on disk. Review it before execution.')
        return deepcopy(ref)

    def context(self):
        base = self.references.load()
        with self.lock:
            data = self._load()
            preferences = [p for p in data['preferences'] if p['base_id'] == base['id']][-8:]
        return dict(method='Developer-preferred measured corrections; exact taught context only.',
                    base_id=base['id'], preferences=deepcopy(preferences),
                    limitations='No generalization to a moved plate; no weight training; no inferred grasp success.')

    def public(self):
        try:
            current = self.reference()
            base = self.references.load()
            with self.lock:
                data = self._load()
            proposals = [p for p in data['proposals'] if p['base_id'] == base['id']]
            return dict(ok=True, blocker='', current=current, proposals=proposals[-12:],
                        preferences=self.context()['preferences'], outcomes=data['outcomes'][-10:])
        except (TeachingError, OSError, ValueError, KeyError) as error:
            return dict(ok=True, blocker=str(error) if isinstance(error, TeachingError) else
                        'Saved learning data needs developer review.', current=None, proposals=[], preferences=[], outcomes=[])

    def capture(self, body):
        with self.lock:
            if self.runner().active:
                raise TeachingError('Finish the current action before capturing a correction.')
            if body.get('manually_demonstrated') is not True:
                raise TeachingError('Demonstrate the improved endpoint by hand, then hold still to capture.')
            action = body.get('action')
            if action not in ('Descend', 'Grip'):
                raise TeachingError('Choose Descend or Grip.')
            previous = self.reference()
            if body.get('reference_id') != previous['id']:
                raise TeachingError('The reference changed. Refresh the comparison first.')
            base = self.references.load()
            samples = []
            began = time.monotonic()
            for _ in range(3):
                state = self.service().status()
                if not state.get('connected') or not state.get('ok') or state.get('errors'):
                    raise TeachingError('Resolve the controller alert before capturing a correction.')
                samples.append(dict(at=utc_now(), endpoint=state.get('endpoint'),
                                    pose_mm=numbers(state.get('pose_mm'), ('X','Y','Z','Rz')),
                                    E1=numbers(state.get('external_axes'), ('E1',))['E1']))
                time.sleep(.15)
            last = samples[-1]
            if time.monotonic()-began > 3:
                raise TeachingError('Position reads took too long. Hold still and capture again.')
            if any(not close_pose(p['pose_mm'], last['pose_mm'], .1) or abs(p['E1']-last['E1']) > .02 for p in samples):
                raise TeachingError('The arm or jaws moved during capture. Hold still, then capture again.')
            endpoints = {p.get('endpoint') for p in previous['records'] if p.get('endpoint')}
            if endpoints and any(p['endpoint'] not in endpoints for p in samples):
                raise TeachingError('This correction came from a different controller connection.')
            corrected = deepcopy(previous)
            if action == 'Descend':
                pose = last['pose_mm']
                if not close_pose({**pose, 'Z':previous['end']['Z']}, previous['end']):
                    raise TeachingError('Only a vertical descent correction is supported; keep X, Y and wrist angle at the taught values.')
                dz = pose['Z']-previous['end']['Z']
                if not .02 <= abs(dz) <= 10:
                    raise TeachingError('Capture a changed descent endpoint within 10 mm of the current endpoint.')
                if not .5 < previous['start']['Z']-pose['Z'] <= 300:
                    raise TeachingError('The corrected descent must remain below the aligned starting point.')
                if abs(last['E1']-previous['e1_start']) > .05:
                    raise TeachingError('Keep the taught open-jaw position while demonstrating descent.')
                corrected['end']['Z'] = pose['Z']
                change = dict(end_z_before=previous['end']['Z'], end_z_after=pose['Z'])
            else:
                if not close_pose(last['pose_mm'], previous['end']):
                    raise TeachingError('Demonstrate Grip at the current descent endpoint.')
                e1 = last['E1']
                if not 0 <= e1 < previous['e1_start']-.01 or not .005 <= abs(e1-previous['e1_end']) <= .5:
                    raise TeachingError('Capture a changed jaw endpoint within 0.5 mm of the current target, below the taught open position.')
                corrected['e1_end'] = e1
                change = dict(e1_before=previous['e1_end'], e1_after=e1)
            note = body.get('note', '')
            if not isinstance(note, str) or len(note) > 1000:
                raise TeachingError('Keep the feedback note under 1000 characters.')
            proposal_id = uuid4().hex
            corrected.pop('id', None)
            corrected['coactive'] = dict(base_id=base['id'], parent_id=previous['id'], proposal_id=proposal_id,
                                         action=action, measured_samples=samples, note=note)
            corrected['id'] = digest(corrected)
            proposal = dict(id=proposal_id, at=utc_now(), action=action, base_id=base['id'],
                            parent_id=previous['id'], status='pending', previous=previous,
                            reference=corrected, change=change, note=note)
            data = self._load()
            data['proposals'].append(proposal)
            self._save(data)
            return dict(ok=True, proposal=proposal, message='Measured correction saved for review. No movement or reference change.')

    def decide(self, body):
        with self.lock:
            if self.runner().active:
                raise TeachingError('Finish the current action before reviewing a correction.')
            data = self._load()
            proposal = next((p for p in data['proposals'] if p['id'] == body.get('proposal_id')), None)
            if not proposal or proposal['status'] != 'pending':
                raise TeachingError('Select a pending correction.')
            decision = body.get('decision')
            if decision not in ('accept', 'reject'):
                raise TeachingError('Choose accept or reject.')
            if decision == 'accept':
                if body.get('reviewed_clear_path') is not True:
                    raise TeachingError('Review the measured change and verify the vertical path and jaw clearance.')
                if self.reference()['id'] != proposal['parent_id'] or self.references.load()['id'] != proposal['base_id']:
                    raise TeachingError('This proposal is stale. Demonstrate against the current reference.')
                data['accepted'] = dict(base_id=proposal['base_id'], reference=proposal['reference'])
                data['preferences'].append(dict(at=utc_now(), base_id=proposal['base_id'],
                    previous_id=proposal['parent_id'], preferred_id=proposal['reference']['id'],
                    action=proposal['action'], change=proposal['change'], note=proposal['note']))
            proposal.update(status='accepted' if decision == 'accept' else 'rejected', reviewed_at=utc_now())
            self._save(data)
            self.invalidate()
            return dict(ok=True, message='Preference saved. The next requested action uses the accepted reference.' if decision == 'accept' else 'Correction rejected; current reference retained.')

    def outcome(self, action, reference_id, result):
        with self.lock:
            data = self._load()
            data['outcomes'].append(dict(at=utc_now(), action=action, reference_id=reference_id, result=deepcopy(result)))
            self._save(data)
