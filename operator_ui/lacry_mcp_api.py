"""Local authenticated tool boundary. No model calls, approvals or raw motion."""
from copy import deepcopy
import hmac
import json
from pathlib import Path
import secrets
import threading
from uuid import uuid4

from flask import Blueprint, jsonify, request
from jsonschema import Draft202012Validator
from researcher_teaching import TeachingError
from lacry_recovery import RequestJournal, REQUEST_ID, refusal

TOKEN_PATH = Path(__file__).parent / 'logs/lacry_codex/mcp-token'
PREFIX = '/researcher/api/lacry/mcp'


def local_token(path=TOKEN_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open('x', encoding='utf-8') as stream:
            stream.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    token = path.read_text(encoding='utf-8').strip()
    if len(token) < 48:
        raise RuntimeError('Invalid local Lacry MCP credential.')
    return token


def catalog(agent):
    from lacry_agent import TOOLS
    # These are the same named planning/read tools the embedded agent used.
    # Confirmation, controller startup and raw motion are deliberately absent.
    return deepcopy(TOOLS + agent.lab_api.tools()) + [
        dict(name='lacry_state', description='Read current Lacry plan, questions, links and execution status.',
             input_schema=dict(type='object', properties={}, additionalProperties=False)),
        dict(name='lacry_stop', description='Request Stop for the current lab workflow. Not a physical E-stop.',
             input_schema=dict(type='object', properties={}, additionalProperties=False)),
        dict(name='lacry_recovery_status', description='Inspect persistent MCP request receipts and automatic recovery policy. Read this after a transport failure, then inspect lacry_state before planning further work. Never restarts or repeats hardware.',
             input_schema=dict(type='object', properties=dict(request_id=dict(type='string', pattern='^[0-9a-f]{32}$',
                 description='Optional exact request ID from an interrupted call; returns its saved result without repeating it.')),
                 additionalProperties=False))]


def register(app, agent, dispatch_lock, token=None, journal=None):
    token = token or local_token()
    journal = journal or RequestJournal(TOKEN_PATH.parent/'requests.sqlite3')
    agent.cancel_mcp_waiters = journal.cancel_waiters
    tool_lock = threading.Lock()
    api = Blueprint('lacry_mcp', __name__, url_prefix=PREFIX)

    @api.errorhandler(TeachingError)
    def refused(error):
        return jsonify(refusal('request_refused', str(error))), error.status

    @api.errorhandler(Exception)
    def failed(error):
        app.logger.exception('Lacry MCP request failed')
        return jsonify(refusal('outcome_unknown',
            'Lacry tool failed; inspect current state and the backend log. No automatic retry of the operation.',
            outcome='unknown')), 500

    def authenticate():
        if (request.remote_addr not in ('127.0.0.1', '::1') or request.headers.get('Origin')
                or not hmac.compare_digest(request.headers.get('X-Lacry-MCP', ''), token)):
            raise TeachingError('Authenticated local Lacry MCP connection required.', 403)

    @api.get('/tools')
    def lacry_mcp_tools():
        authenticate()
        return jsonify(ok=True, tools=catalog(agent), model_calls=False,
                       recovery=dict(version=1, durable_request_ids=True))

    @api.post('/call')
    def lacry_mcp_call():
        authenticate()
        value = request.get_json(silent=True)
        if (not isinstance(value, dict) or not {'name', 'arguments'} <= set(value)
                or set(value) - {'name', 'arguments', 'request_id'}):
            raise TeachingError('Expected tool name and arguments.', 400)
        ident = value.get('request_id', uuid4().hex)
        if not isinstance(ident, str) or not REQUEST_ID.fullmatch(ident):
            raise TeachingError('Expected a 32-character lowercase hexadecimal request ID.', 400)
        tools = {t['name']: t for t in catalog(agent)}
        name = value['name']
        if not isinstance(name, str) or name not in tools:
            raise TeachingError('Unknown Lacry MCP tool; no command was dispatched.', 400)
        errors = list(Draft202012Validator(tools[name]['input_schema']).iter_errors(value['arguments']))
        if errors:
            raise TeachingError('Invalid tool arguments: ' + errors[0].message, 400)
        try:
            cached = journal.begin(ident, name, value['arguments'])
        except Exception:
            if name != 'lacry_stop':
                raise
            # Cancellation must not depend on healthy logging/storage.
            app.logger.exception('Stop receipt unavailable; requesting Stop anyway')
            payload, status, _ = invoke(name, value['arguments'])
            payload['recovery'] = dict(request_id=ident, receipt_available=False)
            return jsonify(payload), status
        if cached:
            payload, status = cached
            return jsonify(payload), status
        payload, status, queued = invoke(name, value['arguments'])
        try:
            payload, status = journal.finish(ident, payload, status, queued=queued)
        except Exception:
            journal.mark_uncertain(ident)
            if name != 'lacry_stop':
                raise
            app.logger.exception('Stop requested but its receipt could not be saved')
            payload['recovery'] = dict(request_id=ident, receipt_available=False)
        return jsonify(payload), status

    def invoke(name, arguments):
        # Lock contention is the only mutation refusal that can be retried.
        # Unexpected errors are saved as terminal outcomes, never dispatched twice.
        try:
            if name == 'lacry_stop':
                try:
                    journal.cancel_waiters()
                except Exception:
                    app.logger.exception('Stop barrier will be persisted before the next dispatch')
                return dict(content=json.dumps(agent.stop()), is_error=False), 200, False
            if name == 'lacry_recovery_status':
                return dict(content=json.dumps(journal.status(arguments.get('request_id'))), is_error=False), 200, False
            if not tool_lock.acquire(blocking=False):
                return refusal('tool_busy', 'Another Lacry tool is running.', retryable=True), 409, True
            try:
                if not dispatch_lock.acquire(blocking=False):
                    return refusal('control_busy', 'Another lab control owns the backend.', retryable=True), 409, True
                try:
                    if name == 'lacry_state':
                        content, failed = json.dumps(agent.public(), default=str), False
                    else:
                        content, failed = agent._run_tool(name, arguments)
                    try:
                        agent.get_runner().audit('lacry_mcp_tool', tool=name, failed=failed)
                    except Exception:
                        app.logger.exception('Lacry tool completed but audit logging failed')
                    return dict(content=content, is_error=failed), 200, False
                finally:
                    dispatch_lock.release()
            finally:
                tool_lock.release()
        except TeachingError as error:
            return refusal('tool_refused', str(error), outcome='tool_returned_error'), error.status, False
        except Exception:
            app.logger.exception('Lacry MCP tool failed')
            return refusal('outcome_unknown',
                'Lacry tool failed; inspect current state. No automatic retry of the operation.',
                outcome='unknown'), 500, False

    app.register_blueprint(api)
