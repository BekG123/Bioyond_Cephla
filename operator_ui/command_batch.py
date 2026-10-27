"""Compose named maintenance/pickup routines under one confirmed reservation."""
from copy import deepcopy
from pathlib import Path
import json
import time
from uuid import uuid4

from autonomous_squid import AutonomousSquid
from hamilton_workflow import HamiltonWorkflow
from researcher_teaching import TeachingError
from squid_execution import digest

LABELS = {
    'hamilton_initialize': 'Initialize Hamilton',
    'hamilton_self_calibration': 'Hamilton self-calibration',
    'hamilton_channel_calibration': 'Hamilton channel height/squeeze calibration',
    'hamilton_full_calibration': 'Hamilton full calibration: self-calibrate, calibrate channels',
    'arm_full_calibration': 'Arm full calibration and pickup to Home',
}
ROOT = Path(__file__).resolve().parent


class CommandBatch:
    def __init__(self, agent, folder=None):
        self.agent = agent
        self.folder = Path(folder or ROOT/'reports/command_batches')

    def history_check(self):
        for path in self.folder.glob('*/workflow.json'):
            record = json.loads(path.read_text(encoding='utf-8'))
            if record.get('status') in ('confirmed', 'running'):
                raise TeachingError('An earlier command batch has an unresolved outcome. Review its log before starting another.')

    def binding(self):
        instrument = self.agent.backend.instrument
        return dict(session=instrument.session, settings_hash=digest(instrument.settings()))

    def ready(self, plan=None):
        self.history_check()
        HamiltonWorkflow(self.agent).arm_clear()
        self.agent.backend.instrument.preflight()
        if plan and self.binding() != plan['hamilton_binding']:
            raise TeachingError('Hamilton session or settings changed. Request a fresh batch.')

    def propose(self, commands):
        if (not isinstance(commands, list) or not 1 <= len(commands) <= 10
                or any(not isinstance(c, str) or c not in LABELS for c in commands)):
            raise TeachingError('Choose an ordered list of supported Hamilton calibration and arm calibration commands.')
        if commands.count('arm_full_calibration') > 1:
            raise TeachingError('Arm pickup calibration can run once per batch; subsequent pickups need a new empty-gripper setup.')
        if not any(c.startswith('hamilton_') for c in commands):
            raise TeachingError('For arm-only calibration, use the existing full calibration action.')
        agent = self.agent
        with agent.lock:
            if agent.review:
                raise TeachingError('Finish the current inspection first.')
            if agent.get_runner().active or agent.get_runner().reserved:
                raise TeachingError('Another workflow owns the lab.')
            agent.pending = None
        blockers = []
        arm = None
        try:
            self.ready()
            if agent.classic is None:
                raise TeachingError('The shared command sequencer is unavailable.')
            if 'arm_full_calibration' in commands:
                if agent.classic.transport is None:
                    raise TeachingError('Arm calibration needs the commissioned pickup-to-Home connection.')
                arm = agent.propose(['full_calibration'], source='command_batch', _publish=False)
        except Exception as error:
            blockers.append(str(error))
        steps = []
        for command in commands:
            steps.extend(deepcopy(arm['steps']) if command == 'arm_full_calibration' and arm else
                         [dict(kind='command_batch', label=LABELS[command])])
        requirements = list(arm.get('requirements', [])) if arm else []
        requirements += [
            'Hands clear and compatible holders secure; supervise the emergency stop.',
            'The arm starts at Home and remains there while Hamilton operates.',
            'One Yes authorizes every listed command, sequentially in this order. Completion is verified before the next command.',
            'Faults, Stop or uncertain completion stop the batch without retry. Physical Hamilton prompts still require operator attention.',
        ]
        if any(c in commands for c in ('hamilton_self_calibration','hamilton_full_calibration')):
            requirements.append('Follow Hamilton instructions to clear the deck for self-calibration and seat the teaching needle in its holder. Self-calibration does not require a tip rack.')
        if any(c in commands for c in ('hamilton_channel_calibration','hamilton_full_calibration')):
            requirements.append('For channel calibration only, load a full compatible tip rack at the configured site, lid removed. In full calibration, wait until self-calibration finishes and the loading instruction appears.')
        plan = dict(id=uuid4().hex, at=time.time(), dispatch='command_batch',
                    commands=list(commands), actions=['command_batch'], arm_plan=arm,
                    hamilton_binding=self.binding(), steps=steps, requirements=requirements,
                    labels=[LABELS[c] for c in commands], executable=not blockers, blockers=blockers,
                    summary='Then '.join(LABELS[c]+'. ' for c in commands).strip())
        with agent.lock:
            agent.pending = plan
        agent._announce_plan(plan)
        return deepcopy(plan)

    def start(self, plan):
        agent = self.agent
        if not plan.get('executable'):
            raise TeachingError('Batch blocked: '+' '.join(plan.get('blockers', [])))
        self.ready(plan)
        if plan['arm_plan']:
            agent.backend.camera_plate_only(['full_calibration'])
            current = agent._classic_plan()
            if current['steps'] != plan['arm_plan']['steps']:
                raise TeachingError('Arm calibration sequence changed. Request a new batch.')
        with agent.lock:
            if not agent.pending or agent.pending['id'] != plan['id']:
                raise TeachingError('This batch confirmation has already been used.')
        folder = self.folder/plan['id']
        folder.mkdir(parents=True, exist_ok=False)
        path = folder/'workflow.json'
        record = dict(plan=deepcopy(plan), status='confirmed', events=[], confirmed_at=time.time())
        def save(event, **fields):
            record['events'].append(dict(at=time.time(), event=event, **fields))
            AutonomousSquid.write(path, record)
        save('confirmed')
        def task(command):
            label = LABELS[command]
            def start():
                def execute(run):
                    if run.stopped():
                        raise TeachingError('Batch stopped before '+label)
                    if self.binding() != plan['hamilton_binding']:
                        raise TeachingError('Hamilton session or settings changed during the batch.')
                    HamiltonWorkflow(agent).arm_clear()
                    record['status'] = 'running'
                    save('command_started', command=command)
                    def progress(state):
                        HamiltonWorkflow(agent).arm_clear()
                        if state.get('message'):
                            with agent.lock:agent.run_state['message']=state['message']
                    result = agent.backend.instrument.run_action(command.removeprefix('hamilton_'), run.stopped, progress)
                    if result.get('ok') is not True or run.stopped():
                        raise TeachingError(label+' did not verify completion.')
                    HamiltonWorkflow(agent).arm_clear()
                    save('command_completed', command=command, result=result)
                    return result
                return agent.get_runner().start('lacry_batch_hamilton', execute)
            timeout = agent.backend.instrument.settings().get('timeout_s',3600)
            return dict(label=label, start=start, timeout_s=3*timeout+120)
        commands = plan['commands']
        arm_index = commands.index('arm_full_calibration') if plan['arm_plan'] else None
        before = [task(c) for c in commands[:arm_index]] if arm_index is not None else []
        after = [task(c) for c in commands[arm_index+1:]] if arm_index is not None else [task(c) for c in commands]
        def finish(final):
            record.update(status='completed' if final.get('ok') else 'stopped_or_failed',
                          finished_at=time.time(), result=deepcopy(final))
            save('finished')
            with agent.lock:
                agent.run_state = deepcopy(final)
            agent._say('lacry', final['message'])
        with agent.lock:
            agent.pending = None
            agent.run_meta = dict(name='Command batch', total_steps=len(plan['steps']))
            agent.run_state = dict(active=True, step=plan['steps'][0]['label'], done=[], ok=None,
                                   error='', message='Running the confirmed command batch.')
        try:
            agent.classic.start(on_finish=finish, include_pickup=arm_index is not None,
                                prefix_steps=before, tail_steps=after,
                                completion_message='All requested commands completed. The arm is at Home.')
        except Exception as error:
            finish(dict(active=False, ok=False, done=[], error=str(error), step=None, message=str(error)))
            raise
        return dict(ok=True, message='Running the complete command batch in order. No further Yes is needed while steps succeed.')
