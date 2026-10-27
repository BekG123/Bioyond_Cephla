"""Headless UI regression with fixture-only APIs, no robot connection."""
import asyncio
import base64
import json
import logging
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import sys
import urllib.request
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import make_server
import websockets

UI=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(UI))
from lacry_memory import LacryMemory,register_memory_api
OUTPUT=UI/'reports/researcher_ui'
app=Flask(__name__,static_folder=str(UI/'static'))
memory_temp=tempfile.TemporaryDirectory(prefix='lacry_memory_ui_')
fixture_memory=LacryMemory(Path(memory_temp.name)/'memory.sqlite3')
fixture_memory.add('Hamilton route','Use Home between stations.',status='approved')
register_memory_api(app,fixture_memory)
posts=[]
hamilton_plans=[]
hamilton_instruction={}
hamilton_responses=[]
hamilton_camera_reads=[]
state=dict(ok=True,configured=True,busy=False,transcript=[],activity=[],pending=None,review=None,
           capabilities=dict(automatic_squid=True),
           links={},running=dict(active=False,ok=None,done=[]))
sequence=dict(active=False,name='',state='idle',log=[])

@app.get('/')
def index():return send_from_directory(UI/'static','lacry.html')

@app.get('/memory-demo')
def memory_demo():
    html=(UI/'static/index.html').read_text(encoding='utf-8')
    panel=html[html.index('<div class="card" id="lacry-memory"'):html.index('<div class="card" id="haiku-pickup"')]
    return '<!doctype html><html><body>'+panel+'<script src="/static/lacry_memory.js"></script></body></html>'

@app.get('/researcher/api/lacry/state')
def agent_state():return jsonify(state)

@app.get('/researcher/api/status')
def status():return jsonify(connected=True,robot='Ready',camera='Connected',hand_guiding=dict(state='off'))

@app.get('/seq')
def seq():return jsonify(sequence)

@app.get('/frame')
def frame():return '',404

@app.get('/researcher/api/lacry/hamilton/status')
def hamilton_fixture():
    if hamilton_instruction.get('mirror'):
        return jsonify(connected=True,global_state='CalibrationAssayRunning',message='Touchscreen calibration.',
            operation=dict(action='full_calibration',status='aborted'),prompt=None,
            touchscreen=dict(fresh=hamilton_instruction.get('fresh',True),session='mirror-session',prompt=hamilton_instruction.get('prompt')))
    if hamilton_instruction:
        return jsonify(connected=True,global_state='CalibrationAssayRunning',message='Waiting for setup.',
            operation=dict(request_id='native-dialog-test',action='full_calibration',status='running',step=hamilton_instruction.get('step','self_calibration'),completed_steps=[]),
            prompt=hamilton_instruction.get('prompt'))
    return jsonify(connected=True,serial='PRPGD2427',global_state='Idle',initialized=False,
        polling=state.get('links',{}).get('hamilton',{}).get('polling',{}),
        message='Hamilton Idle; not initialized.',protocol_catalog=[dict(id=1002,name='Water protocol')],
        recipes=[],maintenance=[dict(name='Database Backup',status='Complete')],
        calibration=dict(ready=True,message='Channel calibration passed.',latest=dict(status='Pass',calibrationDate='2026-10-24T19:38:17')),
        calibration_defaults=dict(tip_site=7,tip_labware_id=273),
        arm_travel=dict(travel_verified=True,empty_travel_verified=False,message='Accepted revised Home-Hamilton travel verified.'),
        arm_handling_history=dict(completed_supervised=True,message='Completed supervised drop-off and retrieval are recorded.'),
        errors=dict(items=[dict(date='Earlier today',message='Front Channel channel motor stalled')]),
        operation=dict(action='protocol',status='aborted'),prompt=None)

@app.get('/researcher/api/lacry/hamilton/camera')
def hamilton_camera_fixture():
    hamilton_camera_reads.append(time.time())
    return '',404

@app.post('/researcher/api/lacry/<path:action>')
def action(action):
    posts.append(action)
    if action=='question/answer':
        body=request.get_json()
        assert body['question_id']==state['question']['id']
        assert body['answer'] in ('Yes','No','Site 7','235938')
        state['question']=None
        state['transcript'].append(dict(role='researcher',text=body['answer']))
        return jsonify(state)
    if action=='hamilton/plan':hamilton_plans.append(request.get_json())
    if action=='hamilton/respond':
        body=request.get_json()
        expected=dict(prompt_id=hamilton_instruction['prompt']['id'],response='Ok',ready=True)
        if hamilton_instruction.get('mirror'):
            expected.update(source='touchscreen',session='mirror-session',token=hamilton_instruction['prompt']['token'])
            if hamilton_instruction['prompt'].get('data',{}).get('inputType')=='tiprack':expected['tip_site']=4
        assert body==expected,(body,expected)
        hamilton_responses.append(body)
        hamilton_instruction['prompt']=None
    if action=='link/squid':
        state['links']['squid']=dict(connected=True,available=True,status='idle',
            simulation=True,message='Squid mock ready; no imaging run in progress.')
    elif action=='button/automatic_experiment':
        state['pending']=dict(id='automatic-fixture',summary='Calibrate, image and retrieve using current Squid settings.',
            steps=[dict(label=s) for s in ['Calibrate','Drop off','Start imaging','Wait for imaging','Retrieve to Home']],
            requirements=['One Yes covers this whole experiment.'])
    elif action=='button/full_calibration':
        state['pending']=dict(id='fixture',summary='Calibrate, align, descend, grip, lift 5 mm slowly, then return Home.',
            steps=[dict(label=s) for s in ['Calibrate','Align','Descend','Grip','Lift the plate 5 mm','Return Home']],requirements=['Hands clear; loaded Home route clear.'])
    elif action in ('button/move_scope','button/move_hamilton','button/transfer_hamilton_squid','button/rehearse_five'):
        route={'button/move_scope':'Home → Squid','button/move_hamilton':'Home → Hamilton',
               'button/transfer_hamilton_squid':'Hamilton → Home → Squid',
               'button/rehearse_five':'5 rounds: Home → Hamilton → Home → Squid → Home; keep plate held'}[action]
        state['pending']=dict(id='fixture',summary=route,steps=[dict(label=route)],requirements=['Route clear.'])
    elif action in ('button/squid_dropoff','button/squid_retrieve','button/hamilton_dropoff','button/hamilton_retrieve'):
        station='Hamilton' if 'hamilton' in action else 'Squid'
        summary=(f'Leave the plate at {station}, then return Home empty.' if action.endswith('dropoff')
                 else f'Retrieve the plate from {station} and bring it Home.')
        state['pending']=dict(id='squid-fixture',summary=summary,executable=True,
            steps=[dict(label=s) for s in ['Travel to Squid','Handle the plate','Lift slowly','Return Home']],
            requirements=['Route clear; imaging completion confirmed for retrieval.'])
    elif action=='cancel':
        assert request.json['plan_id']==state['pending']['id']
        state['pending']=None
    elif action in ('chat','confirm'):
        if action=='chat':assert request.json==dict(message='Yes, start')
        else:assert request.json==dict(plan_id=state['pending']['id'],ready=True)
        assert state['pending'] and state['pending'].get('executable',True)
        state['pending']=None
        state['experiment']=dict(name='Full Calibration',total_steps=6)
        state['running']=dict(active=True,ok=None,step='Align',done=['Calibrate'],message='Aligning with the plate.')
        sequence.update(active=True,name='researcher_align',state='running',log=[dict(t=0.,msg='align started')])
        state['transcript'].extend([dict(role='researcher',text='Yes'),
            dict(role='lacry',text='Full Calibration is running. Keep hands clear.')])
    elif action=='stop':
        state['running'].update(active=False,ok=False,error='operator stop',message='Stopped during Align.')
        sequence.update(active=False,state='stopped')
    elif action=='review':
        assert request.json==dict(review_id='inspection-token',approved=True)
        state['review']=None
    if action.startswith('button/'):
        state['transcript']=[dict(role='lacry',text=state['pending']['summary']+' Route clear. Reply Yes to start.')]
    return jsonify(ok=True,message='Fixture accepted')

async def check(ws_url,url):
    async with websockets.connect(ws_url,max_size=30000000) as ws:
        serial=0;errors=[]
        async def call(method,params=None):
            nonlocal serial
            serial+=1
            await ws.send(json.dumps(dict(id=serial,method=method,params=params or {})))
            while True:
                message=json.loads(await asyncio.wait_for(ws.recv(),20))
                if message.get('method')=='Runtime.exceptionThrown':errors.append(message['params'])
                if message.get('id')==serial:
                    assert 'error' not in message,message
                    return message.get('result',{})
        async def js(expression):
            value=await call('Runtime.evaluate',dict(expression=expression,returnByValue=True,awaitPromise=True))
            assert 'exceptionDetails' not in value,value
            return value.get('result',{}).get('value')
        async def until(expression):
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if await js(expression):return
                await asyncio.sleep(.1)
            raise AssertionError(expression)
        await call('Runtime.enable')
        await call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1080,deviceScaleFactor=1,mobile=False))
        await call('Page.navigate',dict(url=url))
        if '--hamilton-camera-live' in sys.argv:
            # Read-only smoke check against the already running console. Clicks
            # only the camera tab; never proposes or confirms hardware actions.
            await until("document.readyState==='complete' && document.querySelector('[data-cam=hamilton]')!==null")
            await js("document.querySelector('[data-cam=hamilton]').click()")
            await until("document.getElementById('cam-name').textContent==='Inside Hamilton' && !document.getElementById('cam-image').hidden && document.getElementById('cam-image').src.includes('/lacry/hamilton/camera') && document.getElementById('cam-image').naturalWidth===2592")
            first=await js("document.getElementById('cam-image').src")
            assert await js("!document.getElementById('cam-live').hidden && getComputedStyle(document.getElementById('cam-live')).animationName==='camera-live-fade'")
            await until("document.getElementById('cam-image').src!=="+json.dumps(first)+" && document.getElementById('cam-state').textContent.startsWith('live')")
            OUTPUT.mkdir(parents=True,exist_ok=True)
            clip=await js("(()=>{let r=document.getElementById('cam-image').parentElement.parentElement.getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()")
            shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True,clip=clip))
            (OUTPUT/'hamilton_live_tab.png').write_bytes(base64.b64decode(shot['data']))
            await js("document.querySelector('[data-cam=squid]').click()")
            await until("document.getElementById('cam-image').hidden && document.getElementById('cam-name').textContent==='Squid'")
            assert await js("document.getElementById('cam-live').hidden")
            await asyncio.sleep(2)
            assert await js("document.getElementById('cam-image').hidden"), 'Late Hamilton frame replaced the selected camera'
            assert not errors,errors
            result=dict(ok=True,write_requests=0,checks=['real Hamilton image rendered','frames refresh automatically','live status follows received frames','switching tabs ignores late frames','no JavaScript exceptions'])
            (OUTPUT/'hamilton_live_camera_check.json').write_text(json.dumps(result,indent=2))
            print(json.dumps(result));return
        await until("document.getElementById('state-label')?.textContent==='Ready'")
        await until("document.getElementById('experiment-bars').textContent.includes('No experiment running')")
        assert posts==[],posts
        face=await js("(()=>{let r=document.querySelector('[data-link=squid] .control-face').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};})()")
        await call('Input.dispatchMouseEvent',dict(type='mouseMoved',**face))
        await until("getComputedStyle(document.getElementById('squid-help')).visibility==='visible'")
        overview=await js("(()=>{let r=document.querySelector('.main').getBoundingClientRect();return {x:r.x,y:r.y,width:r.width,height:r.height,scale:1};})()")
        shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True,clip=overview))
        OUTPUT.mkdir(parents=True,exist_ok=True)
        (OUTPUT/'lacry_instruments_hover_desktop.png').write_bytes(base64.b64decode(shot['data']))
        await call('Input.dispatchKeyEvent',dict(type='keyDown',key='Escape',code='Escape',windowsVirtualKeyCode=27))
        await until("getComputedStyle(document.getElementById('squid-help')).visibility==='hidden'")
        await call('Input.dispatchMouseEvent',dict(type='mouseMoved',x=0,y=0))
        await js("document.querySelector('[data-link=squid]').focus()")
        await until("getComputedStyle(document.getElementById('squid-help')).visibility==='visible'")
        assert posts==[],posts
        await js("document.activeElement.blur()")
        await js("document.querySelector('[data-link=squid]').click()")
        await until("document.querySelector('[data-state=squid]').textContent==='connected'")
        assert posts==['link/squid']
        state['links']['squid'].update(status='running',message='Squid mock imaging in progress.')
        await until("document.querySelector('[data-state=squid]').textContent==='connected'")
        await until("document.querySelector('#experiment-bars .indeterminate')!==null")
        assert await js("!document.querySelector('#experiment-bars [role=progressbar]').hasAttribute('aria-valuenow')")
        state['links']['squid'].update(status='completed',completion_confirmed=True,
            job=dict(experiment_id='Mock plate imaging',stats=dict(total_images=1)),message='Squid mock imaging complete.')
        await until("document.querySelector('[data-state=squid]').textContent==='connected'")
        await until("document.querySelector('#experiment-bars [role=progressbar]').getAttribute('aria-valuenow')==='100'")
        state['links']['squid'].update(stage_simulated=False,camera_simulated=True)
        await until("document.querySelector('[data-state=squid]').textContent==='connected'")
        await until("document.getElementById('experiment-bars').textContent.includes('1 simulated images')")
        assert posts==['link/squid']
        state['links']['squid'].update(stage_simulated=True)
        state['links']['squid'].update(connected=False,completion_confirmed=False)
        await until("document.getElementById('experiment-bars').textContent.includes('Connection lost')")
        assert await js("document.querySelector('[data-state=squid]').textContent==='disconnected'")
        assert await js("!document.querySelector('#experiment-bars [aria-valuenow=\"100\"]')")
        state['links']['squid'].update(connected=True,status='historical')
        assert posts==['link/squid']  # Monitoring never starts robot actions.
        posts.clear()
        # Ordinary questions have buttons, but their answers never hit confirm.
        state['pending']=None
        state['question']=dict(id='setup-question',text='Is the rack loaded and the teaching needle seated?',options=['Yes','No'])
        state['transcript']=[dict(role='lacry',text=state['question']['text'])]
        await until("document.querySelector('#chat-question-answer button')?.textContent==='Yes'")
        assert await js("document.querySelectorAll('#chat-question-answer button').length===2 && !document.querySelector('#chat-question-answer input, #chat-question-answer textarea')")
        assert not await js("!!document.getElementById('chat-plan-answer')")
        assert not posts
        await call('Emulation.setDeviceMetricsOverride',dict(width=390,height=844,deviceScaleFactor=1,mobile=False))
        await asyncio.sleep(.2)
        assert await js("document.documentElement.scrollWidth<=innerWidth+1")
        await js("document.getElementById('chat-question-answer').scrollIntoView({block:'center'})")
        shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))
        (OUTPUT/'lacry_question_buttons_mobile.png').write_bytes(base64.b64decode(shot['data']))
        await call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1080,deviceScaleFactor=1,mobile=False))
        await call('Page.reload')
        await until("document.querySelector('#chat-question-answer button')?.textContent==='Yes'")
        await js("let q=document.querySelector('#chat-question-answer button');q.click();q.click()")
        await until("!document.getElementById('chat-question-answer')")
        assert posts==['question/answer']
        assert not state['running']['active'] and state['pending'] is None
        state['question']=dict(id='site-question',text='Which site?',options=['Site 4','Site 7'])
        state['transcript'].append(dict(role='lacry',text='Which site?'))
        await until("document.getElementById('chat-log').textContent.includes('Which site?')")
        assert await js("!document.getElementById('chat-question-answer')")
        await js("document.getElementById('chat-input').value='Site 7';document.getElementById('composer').requestSubmit()")
        await until("document.getElementById('chat-log').textContent.includes('Site 7')")
        state['question']=dict(id='part-question',text='What is the part number?',options=[])
        state['transcript'].append(dict(role='lacry',text='What is the part number?'))
        await until("document.getElementById('chat-log').textContent.includes('What is the part number?')")
        assert await js("!document.getElementById('chat-question-answer') && document.querySelectorAll('#chat-log input, #chat-log textarea').length===0")
        await js("document.getElementById('chat-input').value='235938';document.getElementById('composer').requestSubmit()")
        await until("document.getElementById('chat-log').textContent.includes('235938')")
        assert posts==['question/answer']*3
        posts.clear()
        state['pending']=dict(id='experiment-fixture',executable=False,
            summary='8 cycles: wait at Home, then Hamilton → Home → Squid.',
            steps=[dict(label='Cycle 1/8: Wait at Home until Hamilton confirms this job finished')],
            blockers=['Hamilton finished signal: Coming Soon.'],requirements=[])
        state['transcript']=[dict(role='lacry',text='Experiment preview only. Hamilton finished signal: Coming Soon.')]
        await until("document.getElementById('chat-log').textContent.includes('Coming Soon')")
        await until("document.getElementById('experiment-bars').textContent.includes('Preview only')")
        assert await js("!document.getElementById('plan-ready') && !document.getElementById('plan-confirm')")
        assert await js("!document.getElementById('chat-plan-answer')")
        assert posts==[],posts
        assert await js("JSON.stringify(Array.from(document.querySelectorAll('[data-action]')).map(e=>e.dataset.action).sort())===JSON.stringify(['full_calibration','recover'])")
        assert await js("document.querySelectorAll('.researcher-controls button').length===3 && document.querySelectorAll('#tiles .control-button').length===3")
        assert await js("document.querySelector('#tiles').getBoundingClientRect().top < document.querySelector('.researcher-controls').getBoundingClientRect().top")
        assert await js("!document.querySelector('#tiles .desc, .control-caption, .control-help')")
        assert await js("document.querySelectorAll('[role=tooltip]').length===6")
        assert await js("!document.querySelector('[aria-label=\"Machines for agents\"]') && !document.querySelector('[aria-label=Misc]')")
        assert await js("!document.querySelector('[data-action=move_home]') && !document.getElementById('hand-tile')")
        posts.clear()
        await js("document.querySelector('[data-action=full_calibration]').click()")
        await until("document.getElementById('chat-log').textContent.includes('lift 5 mm slowly, then return Home')")
        assert await js("document.querySelector('[data-action=full_calibration]').textContent.includes('Full Calibration')")
        assert posts==['button/full_calibration']
        await js("document.getElementById('chat-input').value='Yes, start';document.getElementById('composer').requestSubmit()")
        await until("!document.getElementById('running').hidden && document.getElementById('state-label').textContent==='Running'")
        await until("document.getElementById('experiment-bars').textContent.includes('1 of 6 steps complete')")
        assert await js("document.querySelector('#experiment-bars [role=progressbar]').getAttribute('aria-valuenow')==='16'")
        state['experiment'].update(repetitions=20,current_cycle=3,completed_cycles=2)
        await until("document.getElementById('experiment-bars').textContent.includes('2 of 20 cycles complete')")
        await call('Page.reload')
        await until("document.getElementById('experiment-bars').textContent.includes('2 of 20 cycles complete')")
        state['experiment']=dict(name='Full Calibration',total_steps=6)
        state['review']=dict(id='temporary-check',label='Check the plate before continuing')
        await until("document.getElementById('experiment-bars').textContent.includes('Waiting for you')")
        state['review']=None
        assert await js("document.getElementById('running-steps').textContent.includes('Align')")
        assert await js("document.querySelector('[data-action=full_calibration]').disabled && !document.getElementById('stop-button').disabled")
        # Same-length transcript/log replacements must repaint.
        state['transcript']=[dict(role='lacry',text='First message')]
        await until("document.getElementById('chat-log').textContent.includes('First message')")
        state['transcript']=[dict(role='lacry',text='Replaced message')]
        sequence['log']=[dict(t=1.,msg='replacement progress')]
        await until("document.getElementById('chat-log').textContent.includes('Replaced message') && document.getElementById('console-body').textContent.includes('replacement progress')")
        await js("document.getElementById('stop-button').click()")
        await until("document.getElementById('running-title').textContent==='Stopped'")
        assert await js("!document.getElementById('running').hidden && document.getElementById('running-message').textContent==='Stopped during Align.'")
        await until("document.querySelector('#experiment-bars .failed')!==null")
        assert await js("document.getElementById('experiment-bars').textContent.includes('operator stop')")
        shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True))
        OUTPUT.mkdir(parents=True,exist_ok=True)
        (OUTPUT/'lacry_pickup_stopped.png').write_bytes(base64.b64decode(shot['data']))
        state['review']=dict(id='inspection-token',at='different-display-timestamp',
                             label='Confirm the plate is fully supported at Hamilton')
        await until("document.getElementById('review-label').textContent.includes('fully supported at Hamilton')")
        await js("document.getElementById('review-yes').click()")
        await until("document.getElementById('review').hidden")
        assert posts[-1]=='review'
        state['running'].update(ok=True,step=None,done=['Calibrate','Align','Descend','Grip','Lift','Home'],error='',message='Full Calibration complete.')
        await until("document.querySelector('#experiment-bars .complete [role=progressbar]')?.getAttribute('aria-valuenow')==='100'")
        # A refresh must keep the server's count and outcome, not rely on browser memory.
        await call('Page.reload')
        await until("document.getElementById('experiment-bars')?.textContent.includes('6 of 6 steps complete')")
        # Long batches remain compact; polling preserves the operator's fold choice.
        state['experiment']=dict(name='Squid experiment',total_steps=332,repetitions=25,completed_cycles=25)
        state['running'].update(done=['Completed step '+str(n) for n in range(332)],message='25 cycles completed. Plate returned Home.')
        await until("document.getElementById('running-count').textContent==='25 / 25 cycles'")
        assert await js("!document.getElementById('running').open && document.getElementById('running').offsetHeight<200")
        await js("document.querySelector('#running > summary').click()")
        await until("document.querySelectorAll('#running-steps li').length===332")
        await asyncio.sleep(1.5)
        assert await js("document.getElementById('running').open && document.querySelector('.running-history').clientHeight<=320 && document.querySelector('.running-history').scrollHeight>320")
        await js("document.querySelector('#running > summary').focus()")
        await call('Input.dispatchKeyEvent',dict(type='keyDown',key='Enter',code='Enter',windowsVirtualKeyCode=13,text='\r'))
        await call('Input.dispatchKeyEvent',dict(type='keyUp',key='Enter',code='Enter',windowsVirtualKeyCode=13))
        assert await js("!document.getElementById('running').open")
        for width,name in [(1440,'desktop'),(390,'mobile')]:
            await call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1080,deviceScaleFactor=1,mobile=False))
            await js("document.getElementById('running').scrollIntoView({block:'start'})")
            await asyncio.sleep(.25)
            assert await js("document.documentElement.scrollWidth<=innerWidth+1")
            clip=await js("(()=>{let r=document.getElementById('running').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()")
            shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True,clip=clip))
            (OUTPUT/('lacry_completed_'+name+'.png')).write_bytes(base64.b64decode(shot['data']))
        await call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1080,deviceScaleFactor=1,mobile=False))
        state['experiment']=dict(name='Full Calibration',total_steps=6)
        state['running'].update(done=['Calibrate','Align','Descend','Grip','Lift','Home'],message='Full Calibration complete.')
        # Inline controls use the exact pending plan and dispatch only once.
        posts.clear()
        await js("document.querySelector('[data-action=full_calibration]').click()")
        await until("document.querySelectorAll('#chat-plan-answer .control-button .control-face').length===2")
        assert await js("Array.from(document.querySelectorAll('#chat-plan-answer button')).map(b=>b.textContent).join(',')==='Yes,No'")
        await js("document.querySelector('#chat-plan-answer button:last-child').click()")
        await until("!document.getElementById('chat-plan-answer')")
        assert posts==['button/full_calibration','cancel'],posts
        assert not state['running']['active']
        await js("document.querySelector('[data-action=full_calibration]').click()")
        await until("document.getElementById('chat-plan-answer')!==null")
        await js("var yesButton=document.querySelector('#chat-plan-answer button');yesButton.click();yesButton.click();")
        await until("document.getElementById('state-label').textContent==='Running'")
        assert posts.count('confirm')==1,posts
        assert await js("document.querySelector('#chat-log .msg:last-child .bubble').textContent==='Full Calibration is running. Keep hands clear.'")
        assert await js("!document.getElementById('chat-plan-answer')")
        await js("document.getElementById('stop-button').click()")
        await until("document.getElementById('running-title').textContent==='Stopped'")
        # Model Markdown becomes semantic text/list nodes, never executable HTML.
        state['transcript']=[dict(role='lacry',text=(
            '**Transfer plan**\n\n* Pick up at **Hamilton**.\n'
            '  - Confirm the plate is secure.\n* Continue via Home.\n\n'
            '3. Arrive at Squid.\n4. Keep the plate held.\n\n'
            '*No release requested.* Use `E1=3.7` only as a reference.\n'
            '5 * 5 = 25.\n<img src=x onerror="window.chatInjected=true">')),
            dict(role='researcher',text='Keep *my wording* exactly as typed.')]
        await until("document.querySelectorAll('#chat-log .lacry ul li').length===3")
        assert await js("document.querySelector('#chat-log .lacry strong').textContent==='Transfer plan'")
        assert await js("document.querySelector('#chat-log .lacry ol').start===3 && document.querySelectorAll('#chat-log .lacry ol li').length===2")
        assert await js("document.querySelector('#chat-log .lacry em').textContent==='No release requested.'")
        assert await js("document.querySelector('#chat-log .lacry code').textContent==='E1=3.7'")
        assert await js("!document.querySelector('#chat-log img') && !window.chatInjected")
        assert await js("document.querySelector('#chat-log .lacry').textContent.includes('5 * 5 = 25.')")
        assert await js("document.querySelector('#chat-log .researcher .bubble').textContent==='Keep *my wording* exactly as typed.'")
        # Visual QA of the chat, including multiline wrapping at narrow widths.
        state['transcript']=[dict(role='researcher',text='Prepare five transport rounds, keeping the plate held.'),
            dict(role='lacry',text='**Five transport rounds**\n\n* Visit Hamilton.\n* Return Home, then visit Squid.\n* Finish each round at Home.\n\nThe plate stays held throughout. Keep the route clear and supervise the emergency stop.\n\nReply **Yes** when you are ready.')]
        state['pending']=dict(id='visual-five',executable=True,summary='Five transport rounds',steps=[dict(label='Five rounds')],requirements=['Route clear.'])
        await until("document.getElementById('chat-log').textContent.includes('Five transport rounds') && document.getElementById('chat-plan-answer')!==null")
        await js("var draft=document.getElementById('chat-input');draft.value='Keep the plate held throughout all five rounds. Return Home between Hamilton and Squid.';draft.dispatchEvent(new Event('input'));")
        assert await js("document.getElementById('chat-input').scrollWidth<=document.getElementById('chat-input').clientWidth+1")
        for width,name in [(1440,'desktop'),(390,'mobile')]:
            await call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1080,deviceScaleFactor=1,mobile=False))
            await js("window.dispatchEvent(new Event('resize'))")
            await asyncio.sleep(.15)
            clip=await js("(()=>{let r=document.querySelector('.chat').getBoundingClientRect();return {x:r.x+scrollX,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()")
            shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True,clip=clip))
            (OUTPUT/('lacry_chat_'+name+'.png')).write_bytes(base64.b64decode(shot['data']))
            assert await js("document.getElementById('chat-input').scrollWidth<=document.getElementById('chat-input').clientWidth+1")
            assert await js("document.getElementById('chat-log').scrollWidth<=document.getElementById('chat-log').clientWidth+1")
            assert await js("document.documentElement.scrollWidth<=innerWidth+1")
            controls=await js("(()=>{let r=document.querySelector('.researcher-controls').getBoundingClientRect();return {x:r.x,y:r.y+scrollY,width:r.width,height:r.height,scale:1};})()")
            shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True,clip=controls))
            (OUTPUT/('lacry_controls_'+name+'.png')).write_bytes(base64.b64decode(shot['data']))
            header=await js("(()=>{let r=document.querySelector('.topbar').getBoundingClientRect();return {x:0,y:0,width:r.width,height:r.height,scale:1};})()")
            shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=True,clip=header))
            (OUTPUT/('lacry_experiment_status_'+name+'.png')).write_bytes(base64.b64decode(shot['data']))
        # Hamilton opens read-only and shares the existing plan confirmation path.
        await call('Emulation.setDeviceMetricsOverride',dict(width=1440,height=1080,deviceScaleFactor=1,mobile=False))
        before=list(posts)
        await js("document.querySelector('[data-link=hamilton]').click()")
        await until("document.getElementById('hamilton-panel').open && document.getElementById('hamilton-status').textContent.includes('PRPGD2427')")
        assert posts==before
        assert await js("document.getElementById('hamilton-plan-protocol').disabled")
        assert await js("document.getElementById('hamilton-errors').textContent.includes('motor stalled')")
        assert await js("!document.getElementById('hamilton-tip-site') && !document.querySelector('[data-hamilton-action]')")
        assert await js("!document.getElementById('hamilton-panel').textContent.includes('Prepare the instrument')")
        for width,name in [(1440,'desktop'),(390,'mobile')]:
            await call('Emulation.setDeviceMetricsOverride',dict(width=width,height=1080,deviceScaleFactor=1,mobile=False))
            await asyncio.sleep(.1)
            assert await js("document.getElementById('hamilton-panel').scrollWidth<=document.getElementById('hamilton-panel').clientWidth+1")
            shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))
            (OUTPUT/('hamilton_panel_'+name+'.png')).write_bytes(base64.b64decode(shot['data']))
            await js("document.getElementById('hamilton-travel-status').scrollIntoView({block:'start'})")
            shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))
            (OUTPUT/('hamilton_handling_'+name+'.png')).write_bytes(base64.b64decode(shot['data']))
            await js("document.getElementById('hamilton-panel').scrollTop=0")
        await js("document.getElementById('hamilton-close').click()")
        await until("!document.getElementById('hamilton-panel').open")
        assert posts==before
        state['links']['hamilton']=dict(connected=True,global_state='CalibrationAssayRunning',
            polling=dict(mode='reduced',camera_paused=True))
        await until("document.getElementById('hamilton-snapshot').disabled")
        await js("document.querySelector('[data-cam=hamilton]').click()")
        await until("document.getElementById('cam-state').textContent==='paused during calibration'")
        assert await js("document.getElementById('cam-live').hidden")
        camera_count=len(hamilton_camera_reads)
        await asyncio.sleep(2)
        assert len(hamilton_camera_reads)==camera_count
        state['links']['hamilton']['polling']=dict(mode='normal',camera_paused=False)
        await until("!document.getElementById('hamilton-snapshot').disabled")
        await until("document.getElementById('cam-state').textContent!=='paused during calibration'")
        assert len(hamilton_camera_reads)>camera_count
        await js("window.openHamiltonPanel()")
        await until("!document.getElementById('hamilton-park').disabled")
        before_park=len(hamilton_plans)
        await js("document.getElementById('hamilton-park').click()")
        await until("!document.getElementById('hamilton-panel').open")
        assert len(hamilton_plans)==before_park+1 and hamilton_plans[-1]['action']=='park'
        await js("document.querySelector('[data-cam=eye]').click()")
        for action in ('hamilton_dropoff','hamilton_retrieve'):
            before=len(posts)
            await js('window.openHamiltonPanel()')
            await until("!document.querySelector('[data-hamilton-handling="+action+"]').disabled")
            assert await js("document.getElementById('hamilton-travel-status').textContent.includes('Completed supervised')")
            await js("document.querySelector('[data-hamilton-handling="+action+"]').click()")
            await until("!document.getElementById('hamilton-panel').open")
            assert posts[before:]==['button/'+action],posts[before:]
            assert state['pending']['executable'] is True
        # A running Hamilton setup instruction is visible without opening its panel.
        before=list(posts)
        hamilton_instruction['prompt']=dict(id='setup-in-chat',text='Clear the deck and seat the teaching needle. Close the door.',data=dict(buttonText='Next'))
        await until("document.getElementById('chat-hamilton-instruction')!==null")
        assert not await js("document.getElementById('hamilton-panel').open")
        assert posts==before  # Polling must never acknowledge a physical instruction.
        assert await js("document.querySelector('#chat-hamilton-instruction button').textContent==='Next'")
        assert await js("document.getElementById('hamilton-calibration-steps').children.length===2")
        state['transcript'].append(dict(role='lacry',text='Waiting for Hamilton setup.'))
        await until("document.getElementById('chat-log').textContent.includes('Waiting for Hamilton setup.') && document.getElementById('chat-hamilton-instruction')!==null")
        assert await js("document.documentElement.scrollWidth<=innerWidth+1")
        await js("document.getElementById('chat-hamilton-instruction').scrollIntoView({block:'center'})")
        shot=await call('Page.captureScreenshot',dict(format='png',captureBeyondViewport=False))
        (OUTPUT/'hamilton_instruction_chat.png').write_bytes(base64.b64decode(shot['data']))
        await js("let b=document.querySelector('#chat-hamilton-instruction button');b.click();b.click()")
        await until("!document.getElementById('chat-hamilton-instruction')")
        assert len(hamilton_responses)==1
        assert posts[len(before):]==['hamilton/respond']
        hamilton_instruction['prompt']=dict(id='finish-in-chat',text='Calibration successful.',data=dict(buttonText='Finish'))
        await until("document.querySelector('#chat-hamilton-instruction button')?.textContent==='Finish'")
        assert len(hamilton_responses)==1  # Success does not accept Finish automatically.
        await js("document.querySelector('#chat-hamilton-instruction button').click()")
        await until("!document.getElementById('chat-hamilton-instruction')")
        assert len(hamilton_responses)==2
        # The vendor can reuse its completion ID in the next stage.
        hamilton_instruction['step']='channel_calibration'
        hamilton_instruction['prompt']=dict(id='finish-in-chat',text='Channel calibration successful.',data=dict(buttonText='Finish'))
        await until("document.querySelector('#chat-hamilton-instruction')?.textContent.includes('Channel calibration successful.')")
        await js("document.querySelector('#chat-hamilton-instruction button').click()")
        await until("!document.getElementById('chat-hamilton-instruction')")
        assert len(hamilton_responses)==3
        # Unloading is a visible physical instruction, acknowledged exactly once.
        before_unload=list(posts)
        hamilton_instruction['prompt']=dict(id='unload-in-chat',kind='calibration_cleanup',
            text='Hamilton is parked with no tips attached. Remove the tip rack from site 7, close the door, and confirm your hands are clear.',
            data=dict(buttonText='Finish unloading'))
        await until("document.querySelector('#chat-hamilton-instruction button')?.textContent==='Finish unloading'")
        assert await js("document.getElementById('chat-hamilton-instruction').textContent.includes('Remove the tip rack from site 7')")
        assert posts==before_unload
        await js("let u=document.querySelector('#chat-hamilton-instruction button');u.click();u.click()")
        await until("!document.getElementById('chat-hamilton-instruction')")
        assert posts[len(before_unload):]==['hamilton/respond']
        assert hamilton_responses[-1]==dict(prompt_id='unload-in-chat',response='Ok',ready=True)
        hamilton_instruction.update(mirror=True,prompt=dict(id='screen-next',source='touchscreen',token='screen-token',text='Native touchscreen instruction.',data=dict(buttonText='Next')))
        await until("document.querySelector('#chat-hamilton-instruction')?.textContent.includes('Native touchscreen instruction.')")
        before_mirror=list(posts)
        assert await js("document.querySelector('#chat-hamilton-instruction .who').textContent.includes('touchscreen')")
        await js("document.querySelector('#chat-hamilton-instruction button').click()")
        await until("!document.getElementById('chat-hamilton-instruction')")
        assert posts[len(before_mirror):]==['hamilton/respond']
        hamilton_instruction['prompt']=dict(id='rack',source='touchscreen',token='rack-token',text='Load tips.',data=dict(buttonText='Next',inputType='tiprack'))
        await until("document.querySelector('#chat-hamilton-instruction select')!==null")
        await js("document.querySelector('#chat-hamilton-instruction select').value='4';document.querySelector('#chat-hamilton-instruction button').click()")
        await until("!document.getElementById('chat-hamilton-instruction')")
        hamilton_instruction['prompt']=dict(id='stale',source='touchscreen',token='stale-token',text='Obsolete prompt',data=dict(buttonText='Next'))
        hamilton_instruction['fresh']=False
        await asyncio.sleep(3)
        assert not await js("!!document.getElementById('chat-hamilton-instruction')")
        hamilton_instruction.clear()
        await call('Page.navigate',dict(url=url+'/memory-demo'))
        await until("document.getElementById('memory-items')?.textContent.includes('Hamilton route')")
        await js("document.getElementById('memory-title').value='Squid memory';document.getElementById('memory-body').value='Station handling uses taught poses.';document.getElementById('memory-form').requestSubmit()")
        await until("document.getElementById('memory-items').textContent.includes('Squid memory')")
        await js("Array.from(document.querySelectorAll('#memory-items details')).find(e=>e.textContent.includes('Squid memory')).querySelectorAll('button')[1].click()")
        await until("document.getElementById('memory-items').textContent.includes('Squid memory — archived')")
        assert not errors,errors
        result=dict(ok=True,hardware_calls=0,posts=posts,checks=['no action on load','chat confirmation starts plan without confirmation box',
            'inline Yes/No match control buttons; No cancels; double-click Yes dispatches once; blocked and running plans show no start buttons',
            'classic job progress','busy buttons','stop available','persistent exact failure stage',
            'same-length log and transcript refresh','only Full Calibration, Stop and Recover action controls; Machines and Misc removed','multiline chat at desktop/mobile widths',
            'semantic bullets, numbered lists, bold and emphasis; HTML remains inert',
            'Squid connection/progress/mock completion without hardware actions',
            'experiment bars: preview, step counts, inspection, failure, completion, disconnection and page refresh',
            'developer memory add and archive','no JavaScript exceptions'])
        (OUTPUT/'lacry_browser_check.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(result))

if __name__=='__main__':
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server=make_server('127.0.0.1',0,app,threaded=True)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with tempfile.TemporaryDirectory(prefix='lacry_qa_',ignore_cleanup_errors=True) as profile:
            browser=subprocess.Popen([r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe',
                '--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-port=0',
                '--user-data-dir='+profile,'about:blank'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                portfile=Path(profile)/'DevToolsActivePort'
                for _ in range(100):
                    if portfile.exists():break
                    time.sleep(.1)
                port=int(portfile.read_text().splitlines()[0])
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/json',timeout=5) as response:tabs=json.load(response)
                check_url='http://127.0.0.1:5002/researcher' if '--hamilton-camera-live' in sys.argv else f'http://127.0.0.1:{server.server_port}'
                asyncio.run(check(next(t['webSocketDebuggerUrl'] for t in tabs if t['type']=='page'),check_url))
            finally:
                browser.terminate();browser.wait(timeout=10)
    finally:server.shutdown()
