"""Researcher claw controls use the same Lua service as Developer /gripper."""
import time
from researcher_teaching import TeachingError, numbers


class HandClaw:
    def __init__(self, get_service, get_runner, get_draggo, params, prepare):
        self.get_service, self.get_runner, self.get_draggo = get_service, get_runner, get_draggo
        self.params, self.prepare = params, prepare
        self.message = 'Uses the same gripper command as Developer Open.'

    @staticmethod
    def auto_ready(robot, hand):
        return (hand.get('state') == 'off' and not hand.get('blocked') and
                robot.get('control_mode', {}).get('mode') == 'auto' and robot.get('enabled') is True and
                robot.get('program_state', {}).get('state') == 'running')

    def public(self, robot, hand):
        run = self.get_runner()
        active = run.active and run.name == 'hand_claw_open'
        blocker = ''
        if not robot.get('connected') or not robot.get('ok') or robot.get('errors'):
            blocker = 'Connect the robot and resolve controller alerts.'
        elif hand.get('state') not in ('off','active'):
            blocker = 'Resolve hand-guiding status before opening the claw.'
        elif robot.get('control_mode', {}).get('mode') not in ('manual','auto') or robot.get('program_state', {}).get('state') not in ('stopped','running','paused'):
            blocker = 'Controller mode or program status is unavailable.'
        elif run.active:
            blocker = 'Wait for the current action to finish.'
        return dict(active=active, can_open=not blocker, needs_prepare=not self.auto_ready(robot,hand),
                    message=self.message, blocker=blocker)

    @staticmethod
    def arm_sample(service):
        began = time.monotonic()
        pose = numbers(service.pose_mm(), ('X','Y','Z','Rz'))
        joints = numbers(service.joints(), ('J1','J2','J3','J4'))
        if time.monotonic()-began > 1:
            raise TeachingError('Arm position reads are too slow to confirm it is still.')
        return dict(pose=pose, joints=joints)

    @staticmethod
    def still(reference, current):
        p, q = reference['pose'], current['pose']
        if (any(abs(p[k]-q[k]) > .3 for k in ('X','Y','Z')) or
                abs((p['Rz']-q['Rz']+180)%360-180) > .2 or
                any(abs(reference['joints'][k]-current['joints'][k]) > (.3 if k=='J1' else .2)
                    for k in ('J1','J2','J3','J4'))):
            raise TeachingError('The arm changed position. Check it before opening the claw.')

    def settled_arm(self, service):
        reference = self.arm_sample(service)
        time.sleep(.2)
        self.still(reference, self.arm_sample(service))
        return reference

    def start(self, body):
        if body.get('ready') is not True:
            raise TeachingError('Release the arm, keep fingers clear, support any held object, and supervise the E-stop.',400)
        if body.get('action') not in ('open','step'):
            raise TeachingError('Choose Open claw or Open a little.',400)
        service = self.get_service()
        robot = service.status()
        ready = self.public(robot,self.get_draggo().public(robot))
        if not ready['can_open']:
            raise TeachingError(ready['blocker'])
        if ready['needs_prepare'] and body.get('empty_gripper') is not True:
            raise TeachingError('Confirm the gripper is empty: preparing Auto may close the jaws before opening.',400)
        arm = self.settled_arm(service)
        result = self.get_runner().start('hand_claw_open',self.execute,service,body['action'],
                                        body.get('empty_gripper') is True,arm)
        if not result.get('ok'):
            raise TeachingError('The arm controls are busy.')
        return dict(ok=True,message='Claw opening requested using the Developer gripper service. Keep hands clear.')

    def execute(self, run, service, action, empty, arm):
        try:
            def check():
                if run.stopped():
                    raise TeachingError('Stopped before the next controller command.')
                self.still(arm,self.arm_sample(service))
            check()
            robot = service.status()
            hand = self.get_draggo().public(robot)
            if not self.auto_ready(robot,hand):
                if not empty:
                    raise TeachingError('Controller mode changed; empty-gripper confirmation is required before preparing Auto.')
                self.message = 'Preparing Auto for the Developer gripper command. Keep hands clear.'
                run.say(self.message)
                self.prepare(run,service)
            check()
            refusal = service._preflight()
            if refusal:
                raise TeachingError('Controller is not ready for the gripper command: '+str(refusal))
            maximum = self.params()['claw_gap_max_mm']-self.params()['claw_gap_min_mm']
            # Read after program startup, which can reset E1 to zero.
            current = numbers(service.external_axes(),('E1',))['E1']
            if not -.05 <= current <= maximum+.05:
                raise TeachingError('Gripper feedback is outside the configured range.')
            target = maximum if action=='open' else min(maximum,max(0.,current)+.2)
            check()
            self.message = 'Opening claw using the Developer gripper command.'
            run.say(self.message)
            run.audit('manual_claw_command',axis='E1',target_e1_mm=target,
                      source='RobotService.move_gripper',mode='auto',speed=5)
            # Same service as Developer POST /gripper; it owns the motion lock.
            result = service.move_gripper(target,speed=5)
            if not result.get('ok') or result.get('recovered') or result.get('gripper_warning'):
                raise TeachingError('Claw movement was not confirmed. Inspect Developer details before retrying.')
            self.still(arm,self.arm_sample(service))
            measured = numbers(service.external_axes(),('E1',))['E1']
            if abs(measured-target) > .05:
                raise TeachingError('Claw did not reach the requested opening. Inspect it before retrying.')
            run.audit('manual_claw_feedback',e1_mm=measured,mode='auto',hand_guiding_active=False)
            self.message = 'Claw opening complete. Auto remains active; use Start hand-guiding when ready to guide the arm.'
            return dict(ok=True,e1=measured,hand_guiding_active=False,source='RobotService.move_gripper')
        except Exception:
            self.message = 'Claw opening stopped. Check Developer details and the actual claw position before retrying.'
            raise

    def stop(self):
        run = self.get_runner()
        if run.active and run.name == 'hand_claw_open':
            run.request_stop()
        return dict(ok=True,message='Stop requested. The current controller command finishes first; a claw movement already sent is not interrupted.')
