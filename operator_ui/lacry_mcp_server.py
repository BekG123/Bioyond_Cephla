"""MCP stdio adapter to Lacry's existing local hardware owner; no LLM client."""
import asyncio
import json
import os
import time
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler
from uuid import uuid4

from lacry_recovery import READ_ONLY_TOOLS, RETRYABLE_CODES

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, ImageContent, TextContent, Tool, ToolAnnotations

ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS = ('Lacry exposes existing checked lab workflows. Read status and workflow catalog, then propose '
    'the complete requested workflow. Tools do not approve hardware plans. The researcher confirms the '
    'displayed plan in Lacry using Yes. Never infer a barcode, invent a route, retry uncertain motion, or '
    'claim completion without its receipt. HOME is the plate holder; IDLE is the parking position. '
    'No Anthropic API is used. Use lacry_stop for cancellation, not emergency stopping. '
    'Transport recovery is automatic and uses durable request IDs. After an interrupted reply, '
    'use lacry_recovery_status with its request_id to retrieve the result, then read lacry_state. '
    'Do not repeat the original operation with a new request when its outcome is unknown.')
SAFE_TOOLS = READ_ONLY_TOOLS


class BackendFailure(RuntimeError):
    def __init__(self, value):
        self.value = value
        super().__init__(value['message'])


class Backend:
    def __init__(self, base=None, token_path=None):
        self.base = base or os.environ.get('LACRY_MCP_BASE_URL', 'http://127.0.0.1:5002')
        url = urlsplit(self.base)
        if url.scheme != 'http' or url.hostname not in ('127.0.0.1', '::1') or url.username or url.password or url.path not in ('', '/') or url.query or url.fragment:
            raise ValueError('Lacry MCP only supports a local loopback backend.')
        self.token_path = Path(token_path or os.environ.get('LACRY_MCP_TOKEN_PATH') or ROOT/'operator_ui/logs/lacry_codex/mcp-token')
        self.opener = build_opener(ProxyHandler({}))

    def call(self, path, body=None):
        # One ID for the entire transport operation, including every reconnect.
        # The backend commits intent/result receipts before acknowledging them.
        body = None if body is None else dict(body, request_id=uuid4().hex)
        deadline = time.monotonic() + 100
        last = None
        for attempt in range(6):
            try:
                return self.once(path, body, timeout=max(.1, min(90, deadline-time.monotonic())))
            except BackendFailure as error:
                last = error.value
                if not last.get('recovery', {}).get('retryable'):
                    raise
            if attempt == 5 or time.monotonic() >= deadline:
                break
            time.sleep(min(.25 * 2**attempt, 2, max(0, deadline-time.monotonic())))
        last = dict(last)
        last['message'] += ' Automatic reconnection budget exhausted; inspect the saved request before any new operation.'
        last['recovery'] = dict(last['recovery'], retryable=False, budget_exhausted=True,
                                next_action='lacry_recovery_status')
        raise BackendFailure(last)

    def once(self, path, body, timeout):
        token = self.token_path.read_text(encoding='utf-8').strip()
        req = Request(self.base.rstrip('/')+'/researcher/api/lacry/mcp/'+path,
                      data=None if body is None else json.dumps(body).encode(),
                      headers={'X-Lacry-MCP': token, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(req, timeout=timeout) as response:
                value = json.load(response)
                if not isinstance(value, dict):
                    raise ValueError('Invalid backend reply')
                if path == 'tools':
                    if not isinstance(value.get('tools'), list):
                        raise ValueError('Invalid tool catalog')
                elif 'content' not in value or type(value.get('is_error')) is not bool:
                    raise ValueError('Invalid tool reply')
                return value
        except HTTPError as error:
            try:
                payload = json.loads(error.read())
                detail = payload.get('message') or payload.get('error') or 'Backend refused the request.'
            except (ValueError, AttributeError):
                payload = {}
                detail = 'Update/restart the idle Lacry backend to load MCP support.'
            recovery = payload.get('recovery') or {}
            # Generic 409/500 is never evidence that dispatch did not occur.
            retryable = (error.code == 409 and recovery.get('retryable') is True
                         and recovery.get('code') in RETRYABLE_CODES)
            if error.code in (502, 503, 504):
                retryable = True  # Same-ID requests are deduplicated by the host.
            raise BackendFailure(dict(ok=False, message=f'Lacry HTTP {error.code}: {detail}',
                recovery=dict(recovery, request_id=(body or {}).get('request_id'), retryable=retryable,
                              next_action='lacry_recovery_status'))) from None
        except (URLError, TimeoutError, ConnectionError, HTTPException, ValueError):
            # An unreadable/lost reply is not proof the operation failed.
            raise BackendFailure(dict(ok=False,
                message='Lacry connection or reply was interrupted.',
                recovery=dict(code='transport_interrupted', retryable=True,
                    dispatch_outcome='unknown', request_id=(body or {}).get('request_id'),
                    next_action='retry_same_request'))) from None


def content_blocks(value):
    if not isinstance(value, list):
        return [TextContent(type='text', text=value if isinstance(value, str) else json.dumps(value))]
    result = []
    for block in value:
        if block.get('type') == 'image':
            source = block['source']
            result.append(ImageContent(type='image', data=source['data'], mimeType=source['media_type']))
        elif block.get('type') == 'text':
            result.append(TextContent(type='text', text=block['text']))
        else:
            raise ValueError('Unsupported tool content type.')
    return result


def create_server(backend=None, read_only=False):
    backend = backend or Backend()
    server = Server('lacry', version='1.0.0', instructions=INSTRUCTIONS)

    @server.list_tools()
    async def list_tools():
        data = await asyncio.to_thread(backend.call, 'tools')
        return [Tool(name=t['name'], description=t['description'], inputSchema=t['input_schema'],
                     annotations=ToolAnnotations(readOnlyHint=t['name'] in SAFE_TOOLS,
                         destructiveHint=False, openWorldHint=False))
                for t in data['tools'] if not read_only or t['name'] in SAFE_TOOLS]

    @server.call_tool()
    async def call_tool(name, arguments):
        if read_only and name not in SAFE_TOOLS:
            return CallToolResult(isError=True, content=[TextContent(type='text',text='Read-only MCP session.')])
        try:
            value = await asyncio.to_thread(backend.call, 'call', dict(name=name, arguments=arguments))
        except BackendFailure as error:
            return CallToolResult(isError=True, content=[TextContent(type='text', text=json.dumps(error.value))])
        blocks = content_blocks(value['content'])
        if value.get('recovery'):
            blocks.append(TextContent(type='text', text=json.dumps(dict(
                request_receipt=value['recovery'],
                refresh_current_state=value['recovery'].get('receipt_replayed', False)))))
        return CallToolResult(isError=bool(value['is_error']), content=blocks)

    return server


async def main():
    server = create_server(read_only=os.environ.get('LACRY_MCP_READ_ONLY') == '1')
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
