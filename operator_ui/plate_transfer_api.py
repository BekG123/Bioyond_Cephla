"""Local terminal entry points for the existing composed transfer runner.

These are operator controls, not model tools. Starts are single-use and bound
to the exact plan printed by the CLI; status/stop never select the newest run.
"""
from copy import deepcopy
from functools import wraps
import json
import re

from flask import current_app, jsonify, request
from autonomy import TransferError
from researcher_teaching import TeachingError


def register(api, get_agent):
    def terminal_errors(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            try:
                return function(*args, **kwargs)
            except (TransferError, TeachingError) as error:
                # Readiness refusals are expected, including a disconnected arm.
                # Keep the exact blocker without connecting, resetting or retrying.
                return jsonify(ok=False, code='transfer_refused', message=str(error)), getattr(error, 'status', 409)
            except Exception:
                current_app.logger.exception('Terminal plate transfer failed: %s', request.path)
                return jsonify(ok=False, code='console_error', message=(
                    'The console could not complete this request. Check its traceback and '
                    'transfer record before any new start; nothing was automatically retried.')), 500
        return wrapped

    def local():
        if request.remote_addr not in ('127.0.0.1', '::1') or request.headers.get('X-Cephla-Terminal') != 'plate-transfer-v1':
            raise TeachingError('Use the local plate-transfer terminal command.', 403)

    def body(required, optional=()):
        local()
        value = request.get_json(silent=True)
        if not isinstance(value, dict) or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
            raise TeachingError('Invalid plate-transfer arguments.', 400)
        return value

    def identifier(value):
        if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{32}', value):
            raise TeachingError('Invalid transfer plan ID.', 400)
        return value

    @api.post('/plate-transfer/plan')
    @terminal_errors
    def transfer_plan():
        value = body(('destination', 'roundtrip'), ('plate_id',))
        if value['destination'] not in ('Squid', 'Hamilton') or type(value['roundtrip']) is not bool:
            raise TeachingError('Choose Squid or Hamilton and a boolean roundtrip option.', 400)
        if 'plate_id' in value and (not isinstance(value['plate_id'], str) or not value['plate_id']):
            raise TeachingError('Expected barcode must be a nonempty string.', 400)
        agent = get_agent()
        with agent.lock:
            if agent.busy or agent.pending:
                raise TeachingError('Finish or discard the existing Lacry plan first.')
            return jsonify(agent.workflow_composition.propose(
                'Cellvis P24-1.5H-N', 1, value['destination'], value.get('plate_id'), value['roundtrip']))

    @api.post('/plate-transfer/start')
    @terminal_errors
    def transfer_start():
        value = body(('plan_id', 'ready'))
        ident = identifier(value['plan_id'])
        if value['ready'] is not True:
            raise TeachingError('Pass --execute after checking the displayed setup requirements.', 400)
        agent = get_agent()
        with agent.lock:
            if (agent.busy or not agent.pending or agent.pending.get('id') != ident
                    or agent.pending.get('dispatch') != 'workflow_composition'):
                raise TeachingError('Transfer plan changed or was consumed; nothing was dispatched.')
            agent.pending['confirmation_source'] = 'researcher_terminal'
            return jsonify(agent.workflow_composition.start(deepcopy(agent.pending)))

    @api.get('/plate-transfer/status/<plan_id>')
    @terminal_errors
    def transfer_status(plan_id):
        local()
        ident = identifier(plan_id)
        agent = get_agent()
        path = agent.workflow_composition.folder / (ident + '.json')
        if not path.is_file():
            raise TeachingError('No dispatched transfer record for this plan.', 404)
        record = json.loads(path.read_bytes())
        return jsonify(ok=True, plan_id=ident, record=str(path), status=record['status'],
                       steps=record.get('steps', []), error=record.get('error'),
                       plate_id=record.get('plate_id'), plate_destination=record.get('plate_destination'))

    @api.post('/plate-transfer/stop')
    @terminal_errors
    def transfer_stop():
        ident = identifier(body(('plan_id',))['plan_id'])
        agent = get_agent()
        with agent.lock:
            runner = agent.get_runner()
            with runner._lock:
                if (agent.run_meta.get('plan_id') != ident or runner.name != 'lacry_workflow_composition'
                        or not runner.active):
                    return jsonify(ok=True, stop_requested=False, message='This transfer is not active; no other task was stopped.')
                runner.stop_event.set()
            runner.audit('sequence_stop_requested', plan_id=ident, source='researcher_terminal')
        return jsonify(ok=True, stop_requested=True, message='Stop requested for this transfer; use the physical E-stop for immediate stopping.')
