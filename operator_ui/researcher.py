"""Researcher station capture and explicit, verified DragGo controls."""
import time
from flask import Blueprint, jsonify, request, Response
from researcher_teaching import TeachingError


def public_status(robot, camera, sequence, teaching=None):
    teaching = teaching or dict(draft=None, routines=[])
    issues = []
    healthy = bool(robot.get('connected') and robot.get('ok') and not robot.get('errors'))
    busy = bool(sequence.get('active'))
    if not robot.get('connected'):
        robot_label = 'Robot disconnected'
        issues.append('Robot disconnected. Select Connect robot to read its position.')
    elif not robot.get('ok', False):
        robot_label = 'Robot status unavailable'
        issues.append('Robot status unavailable. Ask your developer to check the connection.')
    elif robot.get('errors'):
        robot_label = 'Robot needs attention'
        issues.append('Robot needs attention. Ask your developer to resolve the controller alert.')
    else:
        robot_label = 'Robot connected'
    age = camera.get('age_s')
    if not camera.get('open'):
        camera_label = 'Camera disconnected' if camera.get('error') else 'Camera not connected'
    elif not camera.get('enabled'):
        camera_label = 'Camera released'
    elif camera.get('error') or not isinstance(age, (float, int)) or age > 5:
        camera_label = 'Camera image unavailable'
    else:
        camera_label = 'Camera connected'
    if busy:
        issues.append('The arm is being used in Developer view. Wait for that task to finish.')
    if not teaching['routines']:
        issues.append('No reviewed routine is saved yet. In Teach, capture Home first, then Hamilton.')
    issues.append('Full routine playback is not available yet. Separate taught Descend and Grip actions are in Run.')
    return dict(ok=True, checked_at=time.time(), robot=robot_label, connected=bool(robot.get('connected')),
                camera=camera_label, camera_note='Camera images are not needed for station capture. Depth tools are in Developer view.',
                busy=busy, issues=issues, **teaching,
                capabilities=dict(connect=not robot.get('connected') and not busy,
                                  capture=healthy and not busy, record=False,
                                  run=False, pause=False, stop=False))


def register_researcher(app, read_state, teaching=None, draggo=None, workflow=None, imitation=None, home=None, hand_claw=None, routine_check=None, pickup_planner=None, recorded_return=None, latest_hamilton=None, descent=None, grip=None, lacry=None):
    api = Blueprint('researcher', __name__, url_prefix='/researcher/api')

    def _lacry():
        if lacry is None:
            raise TeachingError('Lacry is not configured on this console.', 503)
        return lacry

    def _lacry_call(what, call):
        """Unexpected faults become a plain sentence, never a bare 500."""
        try:
            return call()
        except TeachingError:
            raise
        except Exception:
            app.logger.exception('Lacry %s failed', what)
            raise TeachingError('That could not be completed. Nothing further was sent to the '
                                'arm; check Developer view before trying again.', 503)

    @api.get('/lacry/state')
    def lacry_state():
        return jsonify(_lacry_call('state', lambda: _lacry().public()))

    @api.get('/lacry/hamilton/status')
    def hamilton_status():
        return jsonify(_lacry().backend.instrument.detail())

    @api.get('/lacry/hamilton/camera')
    def hamilton_camera():
        return Response(_lacry().backend.instrument.call('GET','camera/true',binary=True),
                        mimetype='image/png',headers={'Cache-Control':'no-store'})

    @api.post('/lacry/hamilton/plan')
    def hamilton_plan():
        body=request.get_json(silent=True)
        if not isinstance(body,dict) or set(body)-{'action','protocol','repetitions','tip_site','tip_labware_id','polling_test'}:
            raise TeachingError('Choose a Hamilton operation.',400)
        return jsonify(ok=True,plan=_lacry().hamilton_workflow().propose(**body))

    @api.post('/lacry/hamilton/respond')
    def hamilton_respond():
        body=request.get_json(silent=True) or {}
        if body.get('ready') is not True:raise TeachingError('Confirm the Hamilton instruction first.',400)
        if body.get('source')=='touchscreen':
            _lacry().hamilton_workflow().arm_clear()
            return jsonify(_lacry().backend.instrument.respond_touchscreen(body.get('prompt_id'),body.get('response'),
                body.get('session'),body.get('token'),body.get('tip_site')))
        return jsonify(_lacry().backend.instrument.respond(body.get('prompt_id'),body.get('response')))

    @api.post('/lacry/hamilton/observe')
    def hamilton_observe():
        return jsonify(_lacry().backend.instrument.observe_touchscreen())

    @api.post('/lacry/hamilton/abort')
    def hamilton_abort():
        _lacry().stop()
        return jsonify(_lacry().backend.instrument.abort_owned())

    @api.post('/lacry/chat')
    def lacry_chat():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TeachingError('Refresh the page and try again.', 400)
        return jsonify(_lacry_call('chat', lambda: _lacry().send(body.get('message'))))

    @api.post('/lacry/question/answer')
    def lacry_question_answer():
        body=request.get_json(silent=True)
        if not isinstance(body,dict):raise TeachingError('Answer the displayed question.',400)
        return jsonify(_lacry_call('question answer',lambda:_lacry().answer_question(body)))

    @api.post('/lacry/button/<name>')
    def lacry_button(name):
        return jsonify(ok=True, plan=_lacry_call('button', lambda: _lacry().button(name)))

    @api.post('/lacry/link/<name>')
    def lacry_link(name):
        return jsonify(_lacry_call('link', lambda: _lacry().link(name)))

    @api.post('/lacry/confirm')
    def lacry_confirm():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TeachingError('Refresh the page and try again.', 400)
        return jsonify(_lacry_call('confirm', lambda: _lacry().confirm_from_button(body)))

    @api.post('/lacry/review')
    def lacry_review():
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TeachingError('Refresh the page and try again.', 400)
        return jsonify(_lacry_call('review', lambda: _lacry().approve_review(body)))

    @api.post('/lacry/cancel')
    def lacry_cancel():
        body=request.get_json(silent=True) or {}
        if not isinstance(body,dict):raise TeachingError('Refresh the page and try again.',400)
        return jsonify(_lacry_call('cancel', lambda: _lacry().cancel(body.get('plan_id'))))

    @api.post('/lacry/stop')
    def lacry_stop():
        return jsonify(_lacry_call('stop', lambda: _lacry().stop()))

    @api.errorhandler(TeachingError)
    def teaching_error(error):
        return jsonify(ok=False, message=str(error)), error.status

    @api.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @api.get('/status')
    def status():
        try:
            data = read_state()
            result = public_status(data['robot'], data['camera'], data['sequence'],
                                   teaching.public() if teaching else None)
            if draggo:
                result['hand_guiding'] = draggo.public(data['robot'])
                if data['sequence'].get('active'):
                    result['hand_guiding']['can_start'] = False
                if result['hand_guiding']['state'] in ('unknown', 'changing', 'needs_exit'):
                    result['capabilities']['capture'] = False
            if workflow:
                result['plate_workflow'] = workflow.public()
                if result['plate_workflow']['active']:
                    result['issues'] = [s for s in result['issues'] if 'Developer view' not in s]
                    result['issues'].insert(0, result['plate_workflow']['message'])
            if imitation:
                result['imitation'] = imitation.public(data['robot'])
                if result['imitation']['active']:
                    result['issues'] = [s for s in result['issues'] if 'Developer view' not in s]
                    result['issues'].insert(0, result['imitation']['message'])
            if home:
                result['home'] = home.public(data['robot'], result.get('hand_guiding', {}))
                if result['home']['active']:
                    result['issues'] = [s for s in result['issues'] if 'Developer view' not in s]
                    result['issues'].insert(0, result['home']['message'])
            if hand_claw:
                result['hand_claw'] = hand_claw.public(data['robot'], result.get('hand_guiding', {}))
            if pickup_planner:
                result['pickup_plan'] = pickup_planner.public()
            if recorded_return:
                result['recorded_return'] = recorded_return.public(data['robot'])
            if latest_hamilton:
                result['latest_hamilton'] = latest_hamilton.public(data['robot'])
            if descent:
                result['descent'] = descent.public(data['robot'])
                if result['descent']['active']:
                    result['issues'] = [s for s in result['issues'] if 'Developer view' not in s]
                    result['issues'].insert(0, result['descent']['message'])
            if grip:
                result['grip'] = grip.public(data['robot'])
            return jsonify(result)
        except Exception:
            app.logger.exception('Researcher readiness check failed')
            return jsonify(ok=False, message='Connection or saved-data check unavailable. Try again or ask your developer to check the console.'), 503

    @api.post('/grip/<action>')
    def grip_action(action):
        if grip is None or action not in ('start','stop'):
            raise TeachingError('Grip is unavailable. Refresh after the updated console is loaded.',503)
        if action=='stop':return jsonify(grip.stop())
        return jsonify(grip.start(request.get_json(silent=True) or {}))

    @api.post('/descent/<action>')
    def descend(action):
        if descent is None or action not in ('start', 'stop'):
            raise TeachingError('Descent is unavailable. Ask your developer to reload the console.', 503)
        if action == 'stop':
            return jsonify(descent.stop())
        return jsonify(descent.start(request.get_json(silent=True) or {}))

    @api.post('/connect')
    def connect():
        if teaching is None:
            raise TeachingError('Robot connection is not configured.', 503)
        try:
            service = teaching.get_service()
            if not service.robot.connected:
                result = service.connect()
                if not result.get('ok'):
                    app.logger.warning('Researcher connection failed: %s', result.get('error'))
                    raise TeachingError('Could not connect. Check robot power and Ethernet, and disconnect Bioyond Works before trying again.', 503)
            return jsonify(ok=True, message='Robot connected. Connecting does not enable or move the arm.')
        except TeachingError:
            raise
        except Exception:
            app.logger.exception('Researcher connection failed')
            raise TeachingError('Could not connect. Check robot power and Ethernet, and disconnect Bioyond Works before trying again.', 503)

    @api.post('/recorded-return/<action>')
    def recorded_return_action(action):
        if recorded_return is None or action not in ('start','stop','recover-start','start-pruned'):
            raise TeachingError('Recorded return is unavailable.',404)
        if action == 'stop':
            return jsonify(recorded_return.stop())
        if action == 'recover-start':
            return jsonify(recorded_return.start_recovery(request.get_json(silent=True) or {}))
        if action == 'start-pruned':
            return jsonify(recorded_return.start_pruned(request.get_json(silent=True) or {}))
        return jsonify(recorded_return.start(request.get_json(silent=True) or {}))

    @api.post('/latest-hamilton/<action>')
    def latest_route_action(action):
        if latest_hamilton is None or action not in ('start', 'stop'):
            raise TeachingError('Latest Hamilton route is unavailable.', 404)
        if action == 'stop':
            return jsonify(latest_hamilton.stop())
        return jsonify(latest_hamilton.start(request.get_json(silent=True) or {}))

    @api.post('/home/<action>')
    def return_home(action):
        if home is None or action not in ('start', 'stop', 'area'):
            raise TeachingError('Home return is not configured.', 404)
        if action == 'stop':
            return jsonify(home.stop())
        try:
            body = request.get_json(silent=True) or {}
            if action == 'area':
                body = {**body, 'destination':'home_area'}
            return jsonify(home.start(body))
        except TeachingError:
            raise
        except Exception:
            app.logger.exception('Home route could not start')
            raise TeachingError('Home route could not be verified. Check Developer view before retrying.')

    @api.post('/teaching/<action>')
    def teach(action):
        if teaching is None:
            raise TeachingError('Teaching storage is not configured.', 503)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TeachingError('The request was incomplete. Refresh the page and try again.', 400)
        try:
            if action == 'start':
                result = teaching.start(body)
            elif action == 'capture':
                if draggo:
                    hand = draggo.public(teaching.get_service().status())
                    if hand['state'] in ('unknown', 'changing', 'needs_exit'):
                        raise TeachingError(hand['message'])
                result = teaching.capture(body)
            elif action in {'undo', 'discard', 'save'}:
                result = teaching.edit(action, body)
            else:
                raise TeachingError('This teaching action is not available.', 404)
            return jsonify(ok=True, **result)
        except TeachingError:
            raise
        except Exception:
            app.logger.exception('Researcher teaching action failed: %s', action)
            raise TeachingError('The position or saved data could not be updated. Check the connection and refresh before trying again.', 503)

    @api.post('/hand-guiding/<action>')
    def hand_guiding(action):
        if draggo is None or action not in ('start', 'end'):
            raise TeachingError('Hand-guiding is not configured.', 404)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TeachingError('Refresh the page and try again.', 400)
        return jsonify(draggo.change(action == 'start', ready=body.get('ready')))

    @api.post('/hand-claw/<action>')
    def claw_in_hand_guiding(action):
        if hand_claw is None or action not in ('start', 'stop'):
            raise TeachingError('Manual claw control is not configured.', 404)
        if action == 'stop':
            return jsonify(hand_claw.stop())
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TeachingError('Refresh the page and try again.', 400)
        try:
            return jsonify(hand_claw.start(body))
        except TeachingError:
            raise
        except Exception:
            app.logger.exception('Manual claw opening failed to start')
            raise TeachingError('Claw opening could not start. Check Developer details; no Auto-mode fallback was requested.')

    @api.post('/workflow/<action>')
    def plate_workflow(action):
        if workflow is None:
            raise TeachingError('Plate workflow is not configured.', 503)
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TeachingError('Refresh the page and try again.', 400)
        if action == 'adopt':
            return jsonify(workflow.adopt(body))
        if action == 'stop':
            return jsonify(workflow.stop())
        return jsonify(workflow.start(action, body))

    @api.post('/imitation/<action>')
    def imitate(action):
        if imitation is None:
            raise TeachingError('Imitation is not configured.', 503)
        if action == 'stop':
            return jsonify(imitation.stop())
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            raise TeachingError('Refresh the page before trying again.', 400)
        try:
            return jsonify(imitation.start(action, body))
        except TeachingError:
            raise
        except Exception:
            app.logger.exception('Imitation step could not start')
            raise TeachingError('This step could not start. Check Developer view before retrying.', 503)

    @api.post('/routines/<ident>/pickup-plan')
    def plan_saved_pickup(ident):
        if pickup_planner is None:
            raise TeachingError('Pickup planning is not configured.',503)
        try:
            return jsonify(pickup_planner.start(ident))
        except TeachingError:
            raise
        except Exception:
            app.logger.exception('Pickup log preparation failed')
            raise TeachingError('The continuous pickup evidence could not be loaded. Check Developer view.',503)

    @api.get('/routines/<ident>/check')
    def check_saved_routine(ident):
        if teaching is None or routine_check is None:
            raise TeachingError('Saved-routine checking is not configured.', 503)
        try:
            return jsonify(routine_check(teaching.export(ident)))
        except TeachingError:
            raise
        except Exception:
            app.logger.exception('Saved-routine check failed')
            raise TeachingError('The saved route could not be checked. Ask your developer to inspect the data.', 503)

    @api.get('/routines/<ident>/export')
    def export(ident):
        if teaching is None:
            raise TeachingError('Teaching storage is not configured.', 503)
        try:
            response = jsonify(teaching.export(ident))
            response.headers['Content-Disposition'] = 'attachment; filename="home-hamilton-waypoints.json"'
            return response
        except TeachingError:
            raise
        except Exception:
            app.logger.exception('Researcher routine export failed')
            raise TeachingError('The saved routine could not be read. Ask your developer to check the teaching data.', 503)

    @api.post('/<action>')
    def unavailable(action):
        if action not in {'record', 'save', 'run', 'pause', 'stop'}:
            return jsonify(ok=False, message='This action is not available.'), 404
        return jsonify(ok=False, message='Continuous recording and model playback are not implemented yet. You can capture station positions in Teach.'), 501

    app.register_blueprint(api)
