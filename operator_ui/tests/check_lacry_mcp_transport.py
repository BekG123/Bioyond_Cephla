"""Exercise real stdio MCP, optionally Codex, against an isolated read-only fixture.

Run using .venv-lacry-mcp Python by default, or .venv-realsense Python --codex.
The fixture has no robot/instrument/model API connection.
"""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import socket

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'operator_ui'))
from lacry_recovery import RequestJournal
CALLS=[]
TOOL=dict(name='get_workflow_catalog',description='Read the isolated test workflow catalog. No hardware.',
    input_schema=dict(type='object',properties={},additionalProperties=False))


class Fixture(BaseHTTPRequestHandler):
    journal=None
    drop_reply=False
    def log_message(self,*args):pass
    def reply(self,data,status=200):
        self.send_response(status);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    def do_GET(self):
        if self.headers.get('X-Lacry-MCP')!='fixture-token':return self.reply({'error':'credential required'},403)
        if self.path.endswith('/tools'):return self.reply({'tools':[TOOL]})
        self.reply({'error':'unknown endpoint'},404)
    def do_POST(self):
        if self.headers.get('X-Lacry-MCP')!='fixture-token':return self.reply({'error':'credential required'},403)
        data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if data['name']!='get_workflow_catalog':return self.reply({'error':'read-only fixture'},403)
        cached=self.journal.begin(data['request_id'],data['name'],data['arguments'])
        if cached:return self.reply(*cached)
        CALLS.append(data['name'])
        result=dict(content=json.dumps(dict(simulated=True,hardware_connected=False,
            workflows=['Cellvis slot 1 to Squid','Cellvis slot 1 to Hamilton'],finish_options=['drop-off','roundtrip'])),is_error=False)
        value,status=self.journal.finish(data['request_id'],result,200)
        if self.drop_reply:
            self.close_connection=True
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        self.reply(value,status)


async def mcp_probe(env):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params=StdioServerParameters(command=str(ROOT/'.venv-lacry-mcp/Scripts/python.exe'),
        args=['-B',str(ROOT/'operator_ui/lacry_mcp_server.py')],env=env)
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write) as client:
            initialized=await client.initialize()
            tools=await client.list_tools()
            assert [t.name for t in tools.tools]==['get_workflow_catalog']
            reply=await client.call_tool('get_workflow_catalog',{})
            assert not reply.isError and json.loads(reply.content[0].text)['simulated']
            assert CALLS==['get_workflow_catalog'],CALLS
            if Fixture.drop_reply:
                assert json.loads(reply.content[1].text)['request_receipt']['receipt_replayed']
            refused=await client.call_tool('confirm',{'ready':True})
            assert refused.isError
            print(json.dumps(dict(mcp_initialized=True,server=initialized.serverInfo.name,
                tools_listed=True,tool_called=True,unknown_tool_refused=True,
                lost_reply_recovered=Fixture.drop_reply,tool_invocations=len(CALLS),hardware_connected=False)))


def main():
    with tempfile.TemporaryDirectory(prefix='lacry-mcp-test-') as folder:
        token=Path(folder)/'token';token.write_text('fixture-token')
        Fixture.journal=RequestJournal(Path(folder)/'requests.sqlite3')
        Fixture.drop_reply='--drop-reply' in sys.argv
        http=ThreadingHTTPServer(('127.0.0.1',0),Fixture)
        thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
        env=dict(LACRY_MCP_BASE_URL='http://127.0.0.1:'+str(http.server_port),
                 LACRY_MCP_TOKEN_PATH=str(token),LACRY_MCP_READ_ONLY='1')
        try:
            if '--codex' in sys.argv:
                from lacry_codex import CodexSession
                os.environ.update(env)
                session=CodexSession(folder=Path(folder)/'codex')
                try:
                    reply=session.turn('You are testing Lacry MCP with a read-only fixture. Use only the get_workflow_catalog MCP tool. Do not use shell, edit files, or operate hardware.',
                        [dict(type='text',text='Call get_workflow_catalog now and summarize its simulated workflows and finish options in one sentence.')])
                    assert CALLS==['get_workflow_catalog'],CALLS
                    thread_id=session.thread_id
                    session.close()
                    resumed=CodexSession(folder=Path(folder)/'codex')
                    try:
                        resumed.ensure('Read-only Lacry MCP integration test. Do not execute hardware.')
                        assert resumed.thread_id==thread_id
                        resumed.check_tools()
                    finally:resumed.close()
                    print(json.dumps(dict(codex_auth=session.account_type,mcp_calls=CALLS,reply=reply,
                        resumed_same_thread=True,hardware_connected=False)))
                finally:session.close()
            else:asyncio.run(mcp_probe(env))
        finally:http.shutdown();http.server_close();thread.join(timeout=5)


if __name__=='__main__':main()
