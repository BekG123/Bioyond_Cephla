/* Measured station capture and explicit controller-verified hand-guiding. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const text = (id,value) => { $(id).textContent = value; };
  const show = (id,value) => { $(id).hidden = !value; };
  let state = null, draft = null, routines = [], selected = '', pending = false;
  let generation = 0, checking = false, displayedDraft = '', reviewKey = '';
  let routineCheck = null, checkingRoutine = false;
  function notice(message) { text('notice',message); show('notice',!!message); }
  function selectStage(name) {
    ['prepare','teach','run'].forEach(s => show(s,s === name));
    document.querySelectorAll('[data-stage]').forEach(b => {
      b.classList.toggle('active',b.dataset.stage === name);
      if (b.dataset.stage === name) b.setAttribute('aria-current','step');
      else b.removeAttribute('aria-current');
    });
    $('main').focus({preventScroll:true});
  }
  document.querySelectorAll('[data-stage]').forEach(b => b.onclick = () => selectStage(b.dataset.stage));
  document.querySelectorAll('[data-go]').forEach(b => b.onclick = () => selectStage(b.dataset.go));
  function accept(data) {
    const next = data.draft ? data.draft.id + ':' + data.draft.revision : '';
    if (next !== reviewKey) {
      $('reviewed').checked = false;
      $('automatic-ready').checked = false;
      $('manual-performed').checked = false;
    }
    reviewKey = next; draft = data.draft; routines = data.routines;
  }
  function render() {
    const online = !!state?.ok, cap = state?.capabilities || {};
    const canCapture = online && cap.capture && !pending;
    const home = state?.home;
    text('home-status',home?.active ? home.message : home?.blocker || home?.message || 'Home return is unavailable. Check the connection.');
    $('return-home').disabled = pending || !online || !home?.can_start || !$('home-ready').checked;
    $('home-to-area').disabled = true;
    $('stop-home').disabled = !online || !home?.active;
    const recorded = state?.recorded_return;
    text('recorded-return-queue-status',recorded?.queue?.message || 'Queued replay support has not been checked.');
    $('recorded-return-executor').options[1].disabled = !recorded?.queue?.available;
    $('recorded-return-executor').disabled = pending || recorded?.active;
    text('recorded-return-status',recorded?.active ? recorded.message + ' ('+recorded.progress+'%)' : recorded?.blocker || recorded?.message || 'Recorded path unavailable.');
    text('recorded-return-start',recorded?.direction === 'to_hamilton' ? 'Return to Hamilton' : 'Replay toward Home');
    $('recorded-return-start').disabled = pending || !online || !recorded?.can_start || !$('recorded-return-ready').checked;
    $('recorded-return-stop').disabled = !online || !recorded?.active;
    const imitation = state?.imitation;
    const descent = state?.descent;
    text('imitation-status',descent?.active || !imitation?.active ? descent?.message || 'Refresh after the updated console is loaded.' : imitation.message);
    text('imitation-blocker',descent?.blocker || '');
    $('imitate-descend').disabled = !online || pending || !descent?.can_start || !$('descend-ready').checked;
    $('run-descent').disabled = !online || pending || !descent?.can_start || !$('teach-descend-ready').checked;
    const grip = state?.grip;
    $('run-grip').disabled = !online || pending || !grip?.can_start || !$('teach-grip-ready').checked;
    $('run-grip-again').disabled = !online || pending || !grip?.can_start || !$('grip-ready').checked;
    const gripMessage = grip?.active ? grip.message : grip?.can_start ? 'Ready to grip. Closing does not start a lift.' : grip?.message?.startsWith('Grip contact detected') || grip?.message?.startsWith('Controller fault') ? grip.message : grip?.blocker || 'Grip is unavailable until the updated console is loaded.';
    text('teach-grip-status',gripMessage);text('grip-status',gripMessage);
    $('teach-descent-stop').disabled = !online || !(descent?.active || grip?.active);
    text('teach-descent-status',descent?.blocker || descent?.message || 'Descent is unavailable. Refresh the console.');
    $('imitate-stop').disabled = !online || !(descent?.active || grip?.active || imitation?.active || state?.plate_workflow?.active);
    text('run-setup-status',state?.plate_workflow?.active ? state.plate_workflow.message : state?.plate_workflow?.setup_message || 'Checking calibration readiness...');
    const hand = state?.hand_guiding;
    text('hand-guiding-status',state?.plate_workflow?.active ? 'An automatic step is running. Keep hands clear; hand-guiding controls are unavailable until it finishes.' : online && hand ? hand.message : 'Hand-guiding status unavailable. Check the connection before moving the arm.');
    $('hand-guiding-start').disabled = pending || !online || state?.busy || !hand?.can_start || !$('hand-guiding-ready').checked;
    $('hand-guiding-end').disabled = pending || !online || state?.busy || !hand?.can_end;
    $('hand-guiding-ready').disabled = pending || !!hand?.blocked;
    const claw = state?.hand_claw;
    text('hand-claw-status',claw?.active ? claw.message : claw?.blocker || claw?.message || 'Manual claw control is unavailable.');
    show('hand-claw-empty-label',!!claw?.needs_prepare);
    ['hand-claw-step','hand-claw-open'].forEach(id => { $(id).disabled = pending || !online || !claw?.can_open || !$('hand-claw-ready').checked || (claw?.needs_prepare && !$('hand-claw-empty').checked); });
    $('hand-claw-stop').disabled = !online || !claw?.active;
    text('robot-status',online ? state.robot : 'Robot status unavailable');
    text('camera-status',online ? state.camera : 'Camera status unavailable');
    text('camera-note',online ? state.camera_note : 'Check the app connection, then choose Check again.');
    text('saved-status',online ? routines.length ? routines.length + ' saved routine' + (routines.length === 1 ? '' : 's') : draft ? 'Teaching draft in progress' : 'No routine saved' : 'Saved-data status unavailable');
    $('connect').disabled = pending || !online || !cap.connect;
    text('connect',state?.connected ? 'Connected' : 'Connect robot');
    text('readiness-title',canCapture ? 'Ready to capture station positions' : 'Check before capturing');
    text('readiness-subtitle','Capture stations in Teach. Taught Descend and Grip actions are in Run.');
    const issues = online ? state.issues : ['The app or saved teaching data is unavailable. Choose Check again, or ask your developer to check the console.'];
    $('issues').replaceChildren(...issues.map(s => { const li = document.createElement('li'); li.textContent = s; return li; }));
    if (draft && displayedDraft !== draft.id) {
      $('routine-name').value = draft.name; displayedDraft = draft.id;
    }
    if (!draft) displayedDraft = '';
    $('routine-name').disabled = !!draft || pending;
    show('start-teaching',!draft); $('start-teaching').disabled = pending || !online || state?.busy || !$('routine-name').value.trim();
    const count = draft?.waypoints.length || 0, complete = !!draft?.complete;
    text('record-title',!draft ? 'Start a Home → Hamilton teaching draft' : complete ? 'Home and Hamilton captured' : count ? 'Next: position the arm at Hamilton' : 'First: position the arm at Home');
    text('record-detail',!draft ? 'Opening a draft does not capture or move the arm.' : complete ? 'Review the captured stations below, then save your routine.' : count ? 'Capture intermediate points as needed, then capture Hamilton. Let the arm settle before each capture.' : 'At your chosen Home position, let the arm settle, then select Capture Home.');
    show('capture',!!draft && !complete); text('capture',count ? 'Capture Hamilton' : 'Capture Home'); $('capture').disabled = !canCapture;
    show('waypoint',!!draft && count > 0 && !complete); $('waypoint').disabled = !canCapture;
    const plate = draft?.workflow?.includes('Calibrate');
    const nextStep = draft?.next_station;
    const running = !!state?.plate_workflow?.active;
    const manualStep = plate && ['Descend','Grip'].includes(nextStep);
    show('plate-workflow',true);
    show('adopt-workflow',!!draft && !plate && draft.waypoints.every(p => p.station === 'Home'));
    $('adopt-workflow').disabled = pending || !online || state?.busy;
    // Repeating setup archives the previous attempt on the server.
    const automaticNext = plate && draft.waypoints.some(p => p.station === 'Home');
    show('automatic-controls',true);
    show('automatic-ready-label',!!automaticNext);
    show('guided-help',nextStep === 'Calibrate'); show('alignment-help',nextStep === 'Align');
    show('run-calibration',true); show('run-alignment',true);
    const calibrationSaved = !!draft?.waypoints.some(p => p.station === 'Calibrate');
    const alignmentSaved = !!draft?.waypoints.some(p => p.station === 'Align');
    text('setup-stages-status','Calibrate: ' + (calibrationSaved ? 'recorded' : nextStep === 'Calibrate' ? 'next' : 'waiting') + ' · Align: ' + (alignmentSaved ? 'recorded' : nextStep === 'Align' ? 'next' : 'waiting'));
    text('setup-repeat-help',state?.plate_workflow?.setup_message || 'Refresh after the updated console is loaded.');
    const setupBlocked = pending || !online || !cap.capture || state?.busy || !$('automatic-ready').checked;
    ['run-calibration','run-calibration-again'].forEach(id => { $(id).disabled = setupBlocked || !state?.plate_workflow?.can_calibrate; });
    ['run-alignment','run-alignment-again'].forEach(id => { $(id).disabled = setupBlocked || !state?.plate_workflow?.can_align; });
    $('run-setup-ready').checked = $('automatic-ready').checked;
    show('manual-record-controls',manualStep);
    text('record-manual','Record manual ' + (nextStep || 'action'));
    $('record-manual').disabled = !canCapture || !$('manual-performed').checked;
    const flowMessage = state?.plate_workflow?.message || '';
    text('plate-status',running || /did not finish|Stopped\.|Stop requested/.test(flowMessage) ? flowMessage : plate ? complete ? 'Workflow recorded. Review and save below.' : 'Next: ' + nextStep + (manualStep ? '. Perform the action first, then record it.' : '.') : 'Use the plate workflow to insert calibration, alignment and manual action records.');
    show('stop-automatic',running); show('automatic-stop-help',running);
    const calibrationRunning = running && state?.plate_workflow?.step === 'Calibrate';
    text('stop-automatic',calibrationRunning ? 'Stop calibration' : 'Stop automatic step');
    text('automatic-stop-help','Stop takes effect after the current movement finishes. Use the physical E-stop for an emergency.');
    const guide = state?.plate_workflow?.guidance;
    show('calibration-guidance',online && !!guide && (calibrationRunning || nextStep === 'Align' || nextStep === 'Calibrate'));
    const freshGuide = guide && Date.now()/1000 - guide.checked_at < 5;
    text('guidance-message',guide ? freshGuide || !calibrationRunning ? guide.message : 'Waiting for the current operation to finish. Keep hands clear; the error below is from the last image.' : '');
    const initial = guide?.initial_metrics;
    text('guidance-adjustment',initial ? 'Starting error: XY ' + Number(initial.xy_mm).toFixed(2) + ' mm · height ' + Number(initial.z_mm).toFixed(2) + ' mm · yaw ' + Number(initial.yaw_deg).toFixed(2) + '°' : '');
    const metrics = guide?.metrics;
    text('guidance-errors',metrics ? 'Remaining error: XY ' + Number(metrics.xy_mm).toFixed(3) + ' mm · height ' + Number(metrics.z_mm).toFixed(3) + ' mm · yaw ' + Number(metrics.yaw_deg).toFixed(3) + '°' : '');
    text('guidance-progress',guide ? (guide.config || 'Wide') + ' · ' + guide.observations + ' images · ' + (guide.moves || 0) + ' corrections · ' + Number(guide.elapsed_s || 0).toFixed(1) + ' s · ' + guide.confirmation + '/2 confirming images' : '');
    $('stop-automatic').disabled = pending;
    $('plate-stages').replaceChildren(...(plate ? draft.workflow : []).map(s => {
      const li = document.createElement('li');
      li.textContent = s + (draft.waypoints.some(p => p.station === s) ? ' — recorded' : s === nextStep ? ' — next' : ' — waiting');
      return li;
    }));
    if (plate) {
      text('record-title',complete ? 'Workflow captured' : 'Next: ' + nextStep);
      text('record-detail',manualStep ? 'Perform this action manually first, then record its measured result below.' : nextStep === 'Calibrate' ? 'Place both disks in view, release the arm, and click Calibrate below after confirming readiness. The arm performs the corrections.' : nextStep === 'Align' ? 'Align is a separate automatic step. Keep hands clear while it runs.' : 'Hold the arm still at the station, then capture its position.');
      show('capture',!complete && ['Home','Hamilton'].includes(nextStep));
      text('capture','Capture ' + (nextStep || 'station'));
      show('waypoint',nextStep === 'Hamilton');
    }
    show('undo',!!draft && count > 0); $('undo').disabled = pending || !online || state?.busy;
    show('discard',!!draft); $('discard').disabled = pending || !online || state?.busy;
    show('review',count > 0);
    $('review-steps').replaceChildren(...(draft?.waypoints || []).map(p => {
      const li = document.createElement('li'); li.textContent = p.label + ' · captured ' + new Date(p.captured_at).toLocaleTimeString(); return li;
    }));
    $('reviewed').disabled = !complete || pending || !online;
    $('save').disabled = !complete || !$('reviewed').checked || pending || !online || state?.busy;
    if (!routines.some(r => r.id === selected)) selected = routines[0]?.id || '';
    const signature = JSON.stringify(routines.map(r => [r.id,r.name]));
    if ($('routine-select').dataset.signature !== signature) {
      $('routine-select').dataset.signature = signature;
      const items = routines.length ? routines : [{id:'',name:'No routines saved'}];
      $('routine-select').replaceChildren(...items.map(r => { const option = document.createElement('option'); option.value = r.id; option.textContent = r.name; return option; }));
    }
    $('routine-select').value = selected; $('routine-select').disabled = !online || !routines.length || pending;
    const routine = routines.find(r => r.id === selected);
    const pickupPlan = state?.pickup_plan;
    $('plan-pickup').disabled = !online || !routine || pending || !pickupPlan?.configured || pickupPlan?.active;
    text('pickup-plan-status',pickupPlan?.configured ? pickupPlan.message : 'Connect Haiku in Developer view to interpret the recorded descent, grip and first lift.');
    $('check-routine').disabled = !online || !routine || checkingRoutine;
    if (routineCheck && (routineCheck.routine_id !== selected || routineCheck.revision !== routine?.revision)) routineCheck = null;
    text('routine-check-status',checkingRoutine ? 'Checking saved measurements and IK route; no movement...' : routineCheck?.next_step || 'Select a saved routine, then check it before testing.');
    $('routine-check-issues').replaceChildren(...(routineCheck?.issues || []).map(issue => {
      const li = document.createElement('li'); li.textContent = issue.message; return li;
    }));
    text('routine-detail',routine ? 'Saved ' + new Date(routine.saved_at).toLocaleString() + ' · ' + routine.waypoints.length + ' measured positions · awaiting model playback' : 'Capture and review Home → Hamilton in Teach.');
    show('export',!!routine && online);
    if (routine) $('export').href = '/researcher/api/routines/' + encodeURIComponent(routine.id) + '/export';
    text('run-status',routine ? 'Routine saved · playback pending' : 'Waiting for a saved routine');
    const points = routine?.waypoints || [{label:'Home'},{label:'Hamilton'}];
    text('progress-label','0 / ' + points.length + ' steps');
    $('progress').value = 0;
    $('run-steps').replaceChildren(...points.map((p,i) => {
      const li = document.createElement('li'); li.dataset.number = String(i+1); li.textContent = p.label;
      const small = document.createElement('small'); small.textContent = routine ? 'Saved · not executed' : 'Not captured'; li.append(small); return li;
    }));
    // A future executor must drive actual progress and tested pause/stop behavior.
    ['start-run','pause','stop'].forEach(id => { $(id).disabled = true; });
    text('refresh',checking ? 'Checking…' : 'Check again'); $('refresh').disabled = checking || pending;
  }
  async function refresh() {
    if (pending || checking) return;
    checking = true; const ownGeneration = generation;
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(),10000);
    render();
    try {
      const response = await fetch('/researcher/api/status',{cache:'no-store',signal:controller.signal,headers:{'X-Cephla-View':'researcher'}});
      const data = await response.json();
      if (!response.ok || !data.ok || !Array.isArray(data.routines) || !Array.isArray(data.issues) || !data.capabilities) throw new Error();
      if (ownGeneration === generation) { state = data; accept(data); }
    } catch { if (ownGeneration === generation) state = null; }
    finally { clearTimeout(timeout); checking = false; render(); }
  }
  async function action(path,body,message) {
    if (pending || !state?.ok) return false;
    const manualCapture = path === 'teaching/capture' && ['Descend','Grip'].includes(body.station);
    if (manualCapture) { text('manual-record-feedback','Reading arm and gripper positions…'); show('manual-record-feedback',true); }
    pending = true; generation++; notice(''); render();
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(),30000);
    let success = false;
    try {
      const response = await fetch('/researcher/api/' + path,{
        method:'POST',headers:{'Content-Type':'application/json','X-Cephla-View':'researcher'},body:JSON.stringify(body),signal:controller.signal
      });
      const data = await response.json();
      if (!response.ok || !data.ok) {
        notice(typeof data.message === 'string' ? data.message : 'The action could not finish. Refresh and check the connection.');
      } else {
        if (Array.isArray(data.routines)) accept(data);
        notice(message || data.message || 'Saved.'); success = true;
      }
    } catch {
      notice(path.startsWith('hand-guiding/') ? 'The app did not confirm hand-guiding. Keep the arm supported and check its status before moving. Use the physical E-stop if movement is unsafe.' : 'The app did not confirm the action. Check again before retrying; your latest capture may already be saved.');
    } finally {
      if (manualCapture) text('manual-record-feedback',$('notice').textContent);
      clearTimeout(timeout); pending = false; render();
      // A poll started before the mutation is discarded by generation above.
      if (!checking) await refresh();
    }
    return success;
  }
  function draftBody(extra={}) { return {draft_id:draft?.id,revision:draft?.revision,...extra}; }
  $('hand-claw-ready').onchange = render;
  $('hand-claw-empty').onchange = render;
  async function openHandClaw(kind) {
    const ready = $('hand-claw-ready').checked;
    const empty_gripper = $('hand-claw-empty').checked;
    $('hand-claw-ready').checked = false;
    $('hand-claw-empty').checked = false;
    await action('hand-claw/start',{action:kind,ready,empty_gripper});
  }
  $('hand-claw-step').onclick = () => openHandClaw('step');
  $('hand-claw-open').onclick = () => openHandClaw('open');
  $('hand-claw-stop').onclick = async () => {
    try {
      const response = await fetch('/researcher/api/hand-claw/stop',{method:'POST',headers:{'Content-Type':'application/json','X-Cephla-View':'researcher'},body:'{}'});
      const data = await response.json();
      notice(response.ok && data.ok ? data.message : 'Stop was not confirmed. Use the physical E-stop if needed.');
    } catch { notice('Stop was not confirmed. Use the physical E-stop if needed.'); }
    await refresh();
  };
  $('home-ready').onchange = render;
  $('recorded-return-ready').onchange = render;
  $('recorded-return-start').onclick = async () => {
    const ready = $('recorded-return-ready').checked;
    $('recorded-return-ready').checked = false;
    await action('recorded-return/start',{ready,path_id:state?.recorded_return?.path_id,direction:state?.recorded_return?.direction,executor:$('recorded-return-executor').value},'Recorded path requested. Keep hands clear.');
  };
  $('recorded-return-stop').onclick = async () => {
    try {
      const response = await fetch('/researcher/api/recorded-return/stop',{method:'POST',headers:{'Content-Type':'application/json','X-Cephla-View':'researcher'},body:'{}'});
      const result = await response.json();
      if (!response.ok || !result.ok) throw new Error();
      notice(result.message);
    } catch { notice('Stop was not confirmed. Use the physical E-stop if needed.'); }
    await refresh();
  };
  $('return-home').onclick = async () => {
    const ready = $('home-ready').checked;
    $('home-ready').checked = false;
    await action('home/start',{ready,target_id:state?.home?.target_id});
  };
  $('stop-home').onclick = async () => {
    try {
      const response = await fetch('/researcher/api/home/stop',{method:'POST',headers:{'Content-Type':'application/json','X-Cephla-View':'researcher'},body:'{}'});
      const data = await response.json();
      notice(response.ok && data.ok ? data.message : 'Stop was not confirmed. Use the physical E-stop if needed.');
    } catch { notice('Stop was not confirmed. Use the physical E-stop if needed.'); }
    await refresh();
  };
  $('descend-ready').onchange = render;
  $('teach-descend-ready').onchange = render;
  async function startDescent(confirmation) {
    const ready=$(confirmation).checked;
    $('descend-ready').checked=false;
    $('teach-descend-ready').checked=false;
    await action('descent/start',{ready},'Adjusting claws above the plate, then opening and descending. Keep hands clear.');
  }
  $('imitate-descend').onclick = () => startDescent('descend-ready');
  $('run-descent').onclick = () => startDescent('teach-descend-ready');
  $('teach-descent-stop').onclick = () => $('imitate-stop').onclick();
  $('teach-grip-ready').onchange = render;
  $('grip-ready').onchange = render;
  async function startGrip(confirmation) {
    const ready=$(confirmation).checked,descent_id=state?.grip?.descent_id;
    $('teach-grip-ready').checked=false;$('grip-ready').checked=false;
    await action('grip/start',{ready,descent_id},'Closing to the plate setting. Keep hands clear.');
  }
  $('run-grip').onclick=()=>startGrip('teach-grip-ready');
  $('run-grip-again').onclick=()=>startGrip('grip-ready');
  $('imitate-stop').onclick = async () => {
    // Stop bypasses the ordinary UI pending flag as well as the server lock.
    try {
      const path = state?.grip?.active ? '/researcher/api/grip/stop' : state?.descent?.active ? '/researcher/api/descent/stop' : state?.plate_workflow?.active ? '/researcher/api/workflow/stop' : '/researcher/api/imitation/stop';
      const response = await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Cephla-View':'researcher'},body:'{}'});
      const data = await response.json();
      notice(response.ok && data.ok ? data.message || 'Stop requested; the current movement finishes first.' : data.message || 'Stop was not confirmed. Use the physical E-stop if needed.');
    } catch { notice('Stop was not confirmed. Use the physical E-stop if needed.'); }
  };
  $('connect').onclick = () => action('connect',{},'Robot connected. No movement or enabling was requested.');
  $('hand-guiding-ready').onchange = render;
  $('hand-guiding-start').onclick = async () => {
    if (!$('hand-guiding-ready').checked || !state?.hand_guiding?.can_start) return;
    await action('hand-guiding/start',{ready:true});
    $('hand-guiding-ready').checked = false; render();
  };
  $('hand-guiding-end').onclick = () => action('hand-guiding/end',{});
  $('start-teaching').onclick = () => action('teaching/start',{name:$('routine-name').value.trim(),workflow:'plate_pick_hamilton'},'Draft started. Capture Home, then calibrate and align the plate.');
  $('capture').onclick = () => {
    if (!draft || !state?.capabilities.capture) return;
    const station = draft.next_station || (draft.waypoints.length ? 'Hamilton' : 'Home');
    action('teaching/capture',draftBody({station}),station + ' position captured and saved to your draft.');
  };
  $('waypoint').onclick = () => {
    if (!draft || !state?.capabilities.capture) return;
    action('teaching/capture',draftBody({station:'Waypoint'}),'Intermediate position captured.');
  };
  $('adopt-workflow').onclick = () => action('workflow/adopt',draftBody(),'Plate workflow selected; the existing Home capture is preserved.');
  $('automatic-ready').onchange = render;
  $('run-setup-ready').onchange = () => { $('automatic-ready').checked = $('run-setup-ready').checked; render(); };
  $('manual-performed').onchange = render;
  $('run-calibration').onclick = () => action('workflow/Calibrate',draftBody({ready:$('automatic-ready').checked}));
  $('run-alignment').onclick = () => action('workflow/Align',draftBody({ready:$('automatic-ready').checked}));
  $('run-calibration-again').onclick = $('run-calibration').onclick;
  $('run-alignment-again').onclick = $('run-alignment').onclick;
  $('record-manual').onclick = () => action('teaching/capture',draftBody({station:draft?.next_station,performed:$('manual-performed').checked}),'Manual action and measured position recorded.');
  $('stop-automatic').onclick = () => action('workflow/stop',{},'Stop requested; the current movement finishes first.');
  $('undo').onclick = () => action('teaching/undo',draftBody(),'Last capture removed. Earlier captured positions are unchanged.');
  $('discard').onclick = () => action('teaching/discard',draftBody(),'Draft discarded. Previously saved routines are unchanged.');
  $('save').onclick = async () => {
    if (!draft?.complete || !$('reviewed').checked) return;
    if (await action('teaching/save',draftBody({reviewed:true}),'Routine saved. Model playback is still pending.')) {
      selected = routines[0]?.id || ''; render(); selectStage('run');
    }
  };
  $('reviewed').onchange = render; $('routine-name').oninput = render;
  $('routine-select').onchange = () => { selected = $('routine-select').value; render(); };
  $('plan-pickup').onclick = () => action('routines/' + encodeURIComponent(selected) + '/pickup-plan',{});
  $('check-routine').onclick = async () => {
    if (checkingRoutine || !selected) return;
    const ident = selected;
    checkingRoutine = true; routineCheck = null; render();
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(),10000);
    try {
      const response = await fetch('/researcher/api/routines/' + encodeURIComponent(ident) + '/check',
        {cache:'no-store',signal:controller.signal,headers:{'X-Cephla-View':'researcher'}});
      const data = await response.json();
      if (!response.ok || !data.ok || !Array.isArray(data.issues)) throw new Error(data.message || 'The routine could not be checked. Check Developer details.');
      if (selected === ident) routineCheck = data;
    } catch (error) { notice(error.message || 'Routine check unavailable. No motion was requested.'); }
    finally { clearTimeout(timeout); checkingRoutine = false; render(); }
  };
  $('refresh').onclick = refresh;
  render(); refresh(); setInterval(refresh,1000);
})();
