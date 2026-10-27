"""Inspectable decision evidence, not private model reasoning or replay authority."""
from copy import deepcopy
import hashlib
import json
import logging
import re
from uuid import uuid4

from audit_log import redact

DECISION_GUIDANCE = '''
For developer auditing, when selecting tools, briefly state the action you chose
and the provided facts or settings supporting its parameters. Mention any missing
evidence or assumptions. Give a concise decision summary, not internal reasoning.
Do not invent an explanation or treat your summary as permission to move hardware.
'''


def evidence(value):
    """Keep public API evidence; omit image bytes, credentials and thinking blocks."""
    if isinstance(value, dict):
        if value.get('type') in ('thinking', 'redacted_thinking'):
            return dict(type=value['type'], omitted='private reasoning')
        if value.get('type') == 'base64':
            data = str(value.get('data', ''))
            return dict(type='base64', media_type=value.get('media_type'),
                        omitted='binary payload', encoded_length=len(data),
                        sha256=hashlib.sha256(data.encode()).hexdigest())
        return redact({str(k): evidence(v) for k, v in value.items()})
    if isinstance(value, (list, tuple)):
        return [evidence(v) for v in value]
    if isinstance(value, str):
        # Tool results are often JSON strings: redact their nested fields too.
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            parsed = None
        if isinstance(parsed, (dict, list)):
            return json.dumps(evidence(parsed), ensure_ascii=False)
        return redact(re.sub(r'\bsk-(?:ant-)?[A-Za-z0-9_-]+', '[REDACTED]', value))
    return value


class DecisionTrace:
    def __init__(self, sink):
        self.sink = sink
        self.turn_id = uuid4().hex
        self.round = 0

    def event(self, kind, **fields):
        try:
            self.sink('lacry_decision_' + kind, decision_turn_id=self.turn_id,
                      decision_round=self.round, **evidence(fields))
        except Exception:
            # Auditing must never swallow an error or dispatch/retry an action.
            logging.exception('Lacry decision audit unavailable')

    def complete(self, client, payload):
        self.round += 1
        request = deepcopy(payload)
        request['system'] = request.get('system', '') + DECISION_GUIDANCE
        self.event('request', payload=request)
        try:
            response = client.complete(request)
        except Exception as error:
            self.event('model_error', error_type=type(error).__name__, message=str(error))
            raise
        summaries = [b.get('text', '') for b in response.get('content', [])
                     if b.get('type') == 'text']
        self.event('response', response=response, stated_summary='\n'.join(summaries),
                   summary_status='model_reported_not_verified' if summaries else 'not_provided')
        return response
