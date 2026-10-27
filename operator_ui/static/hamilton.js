/* Hamilton controls share Lacry's plan/confirm path. Opening this panel is read-only. */
(function () {
  'use strict';
  var byId = function (id) { return document.getElementById('hamilton-' + id); };
  var promptId = null, loading = false, recipeSignature = '', defaultTipSite = 7;
  var chatPrompt = null, answeringPrompt = false, answeredPrompt = null;
  var defaultTipLabwareId = 273;
  function rackMismatch(prompt) {
    return !!(prompt && prompt.selection && prompt.selection.tip_labware_id !== defaultTipLabwareId);
  }
  var cameraWasPaused = false;
  var labels = {initialize:'Initialize',self_calibration:'Self-calibration',channel_calibration:'Channel height/squeeze calibration',full_calibration:'Full calibration'};
  function message(text) { byId('status').textContent = text; }
  function api(path, body) {
    return fetch('/researcher/api/lacry/hamilton/' + path, body === undefined ? {} : {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
    }).then(function (response) { return response.json().then(function (data) {
      if (!response.ok || data.ok === false) { throw new Error(data.message || data.error || 'Hamilton request failed.'); }
      return data;
    }); });
  }
  function list(id, rows) {
    var root = byId(id); root.textContent = '';
    (rows.length ? rows : ['None reported']).forEach(function (text) {
      var li = document.createElement('li'); li.textContent = text; root.appendChild(li);
    });
  }
  window.renderHamiltonInstruction = function () {
    var log = document.getElementById('chat-log'), old = document.getElementById('chat-hamilton-instruction');
    if (!chatPrompt || chatPrompt.key === answeredPrompt) { if (old) { old.remove(); } return; }
    if (old && old.dataset.promptId === chatPrompt.key) { return; }
    if (old) { old.remove(); }
    var prompt = chatPrompt, row = document.createElement('div'), wrap = document.createElement('div');
    row.id = 'chat-hamilton-instruction'; row.className = 'msg lacry'; row.dataset.promptId = prompt.key;
    var who = document.createElement('div'); who.className = 'who'; who.textContent = prompt.source === 'touchscreen' ? 'Hamilton touchscreen · live instruction' : 'Lacry · Hamilton needs your attention';
    var bubble = document.createElement('div'); bubble.className = 'bubble';
    var instruction = document.createElement('p'); instruction.textContent = prompt.text;
    var note = document.createElement('p'); note.textContent = 'Answer this Hamilton instruction here when ready.';
    if (prompt.selection) {
      note.textContent = 'Selected rack: ' + prompt.selection.label + ' (' + prompt.selection.reference_id + '), site ' + prompt.selection.tip_site + '. Complete the instruction, then continue.';
    }
    if (rackMismatch(prompt)) {
      note.textContent = 'This run selected the wrong tip rack (' + prompt.selection.label + '). Cancel this calibration before starting a new plan with the configured rack.';
    }
    var rackSite = null;
    if (prompt.source === 'touchscreen' && prompt.data && prompt.data.inputType === 'tiprack') {
      note.textContent = '300 µL framed conductive filtered tips (235903). Select the site you loaded; the camera will check it before this answer is sent.';
      rackSite = document.createElement('select'); rackSite.setAttribute('aria-label','Loaded calibration tip-rack site');
      for (var site = 1; site <= 8; site++) {
        var option = document.createElement('option'); option.value = site; option.textContent = 'Site ' + site; rackSite.appendChild(option);
      }
      rackSite.value = String(defaultTipSite);
    }
    var button = document.createElement('button'), face = document.createElement('span');
    button.type = 'button'; button.className = 'control-button chat-answer'; button.disabled = answeringPrompt || rackMismatch(prompt);
    face.className = 'control-face'; face.textContent = (prompt.data && prompt.data.buttonText) || 'Continue'; button.appendChild(face);
    var error = document.createElement('p'); error.setAttribute('role','alert');
    button.onclick = function () {
      if (answeringPrompt || !chatPrompt || chatPrompt.key !== prompt.key || rackMismatch(prompt)) { return; }
      answeringPrompt = true; button.disabled = true; error.textContent = '';
      var answer = {prompt_id:prompt.id,response:'Ok',ready:true};
      if (prompt.source === 'touchscreen') {
        answer.source = 'touchscreen'; answer.session = prompt.session; answer.token = prompt.token;
        if (rackSite) { answer.tip_site = Number(rackSite.value); }
      }
      api('respond',answer).then(function () {
        answeredPrompt = prompt.key; row.remove();
      }).catch(function (e) { error.textContent = e.message; })
        .finally(function () { answeringPrompt = false; button.disabled = false; refresh(); });
    };
    bubble.appendChild(instruction); bubble.appendChild(note);
    if (rackSite) { bubble.appendChild(rackSite); }
    bubble.appendChild(button); bubble.appendChild(error);
    wrap.appendChild(who); wrap.appendChild(bubble); row.appendChild(wrap); log.appendChild(row);
    log.scrollTop = log.scrollHeight;
  };
  function render(data) {
    message((data.serial ? data.serial + ' · ' : '') + data.message);
    var cameraPaused = !!(data.polling && data.polling.camera_paused);
    byId('snapshot').disabled = cameraPaused;
    if (cameraPaused) {
      byId('camera').hidden = true;
      byId('camera-note').textContent = 'Camera paused during calibration. Status and instructions remain available.';
    } else if (cameraWasPaused) {
      byId('camera-note').textContent = 'Camera available. Capture a new snapshot.';
    }
    cameraWasPaused = cameraPaused;
    if (data.door_automation_ready === false) {
      byId('door-note').textContent = 'Automatic plate handoff needs a supported door-access arrangement. Hamilton requires the door closed for execution; this API does not provide an automatic door actuator.';
    }
    byId('operation').textContent = data.operation ?
      data.operation.action + ' · ' + data.operation.status + (data.operation.error ? ' · ' + data.operation.error : '') : 'No operation started by Lacry.';
    if (data.calibration_defaults) {
      defaultTipSite = data.calibration_defaults.tip_site || 7;
      defaultTipLabwareId = data.calibration_defaults.tip_labware_id || 273;
    }
    var operation = data.operation || {}, steps = byId('calibration-steps'); steps.textContent = '';
    if (operation.action === 'full_calibration') {
      ['self_calibration','channel_calibration'].forEach(function (step) {
        var li = document.createElement('li'), done = (operation.completed_steps || []).indexOf(step) >= 0;
        li.textContent = labels[step] + ' — ' + (done ? 'Complete' : operation.step === step ? operation.status : 'Waiting');
        steps.appendChild(li);
      });
    }
    var busy = data.global_state !== 'Idle' || ['starting','running'].indexOf(operation.status) >= 0;
    byId('park').disabled = !data.connected || busy;
    var travel = data.arm_travel || {}, history = data.arm_handling_history || {};
    byId('travel-status').textContent = (travel.message || 'Saved travel evidence unavailable.') + ' ' +
      (history.message || 'Loaded handling history unavailable.');
    document.querySelectorAll('[data-hamilton-handling]').forEach(function (button) {
      button.disabled = !data.connected || busy ||
        (travel.travel_verified !== true && travel.empty_travel_verified !== true);
    });
    list('protocols', (data.protocol_catalog || []).map(function (x) { return x.name; }));
    list('errors', ((data.errors || {}).items || []).map(function (x) { return x.date + ' · ' + x.message; }));
    var recipes = data.recipes || [], signature = JSON.stringify(recipes);
    if (signature !== recipeSignature) {
      recipeSignature = signature;
      var selected = byId('protocol').value;
      byId('protocol').textContent = '';
      if (!recipes.length) { var empty = document.createElement('option'); empty.value = ''; empty.textContent = 'No commissioned recipes'; byId('protocol').appendChild(empty); }
      recipes.forEach(function (name) { var option = document.createElement('option'); option.value = name; option.textContent = name; byId('protocol').appendChild(option); });
      if (recipes.indexOf(selected) >= 0) { byId('protocol').value = selected; }
    }
    byId('plan-protocol').disabled = !recipes.length;
    byId('recipes-note').textContent = recipes.length ? 'Recipe setup includes the reviewed deck and tip/liquid capacity.' : 'No commissioned liquid-handling recipe yet. Define and verify the reservoir, tips, plate and volumes before a live experiment.';
    var mirror = data.touchscreen || {};
    chatPrompt = data.connected && operation.status === 'running' ? data.prompt : null;
    // Hamilton reuses the completion view ID across calibration stages.
    if (chatPrompt) { chatPrompt.key = [operation.request_id, operation.step, chatPrompt.id, JSON.stringify(chatPrompt.selection), defaultTipLabwareId].join(':'); }
    if (!chatPrompt && operation.status !== 'running' && mirror.fresh && mirror.prompt && !mirror.prompt.owner_request) {
      chatPrompt = mirror.prompt; chatPrompt.session = mirror.session;
      chatPrompt.key = [mirror.session,chatPrompt.token].join(':');
    }
    window.renderHamiltonInstruction();
    byId('prompt').hidden = !chatPrompt;
    if (promptId !== (chatPrompt && chatPrompt.id)) { byId('prompt-ready').checked = false; }
    promptId = chatPrompt && chatPrompt.id;
    byId('prompt-ok').disabled = rackMismatch(chatPrompt);
    if (chatPrompt) {
      byId('prompt-text').textContent = chatPrompt.text || JSON.stringify(chatPrompt.data);
      byId('prompt-ok').textContent = (chatPrompt.data && chatPrompt.data.buttonText) || 'Continue';
    }
  }
  function refresh() {
    if (loading) { return; }
    loading = true;
    api('status').then(render).catch(function (error) {
      message('Connection unavailable: ' + error.message);
      chatPrompt = null; window.renderHamiltonInstruction();
    })
      .finally(function () { loading = false; });
  }
  function plan(body) {
    api('plan', body).then(function () { byId('panel').close(); })
      .catch(function (error) { message(error.message); });
  }
  window.openHamiltonPanel = function () { byId('panel').showModal(); refresh(); };
  document.addEventListener('DOMContentLoaded', function () {
    byId('park').onclick = function () { plan({action:'park'}); };
    byId('close').onclick = function () { byId('panel').close(); };
    document.querySelectorAll('[data-hamilton-handling]').forEach(function (button) {
      button.onclick = function () {
        button.disabled = true;
        fetch('/researcher/api/lacry/button/' + button.dataset.hamiltonHandling, {
          method:'POST',headers:{'Content-Type':'application/json'},body:'{}'
        }).then(function (response) { return response.json().then(function (data) {
          if (!response.ok || data.ok === false) { throw new Error(data.message || 'Plate-transfer plan unavailable.'); }
          byId('panel').close();
        }); }).catch(function (error) { message(error.message); })
          .finally(function () { button.disabled = false; });
      };
    });
    byId('snapshot').onclick = function () {
      var img = byId('camera'); img.onload = function () { img.hidden = false; byId('camera-note').textContent = 'Snapshot captured ' + new Date().toLocaleTimeString(); };
      img.onerror = function () { img.hidden = true; byId('camera-note').textContent = 'Deck image unavailable.'; };
      img.src = '/researcher/api/lacry/hamilton/camera?t=' + Date.now();
    };
    byId('plan-protocol').onclick = function () { plan({action:'protocol',protocol:byId('protocol').value,repetitions:Number(byId('cycles').value)}); };
    byId('abort').onclick = function () { api('abort',{}).then(function (d) { message(d.message); }).catch(function (e) { message(e.message); }); };
    byId('prompt-ok').onclick = function () {
      if (!byId('prompt-ready').checked) { message('Complete and confirm the displayed instruction first.'); return; }
      if (rackMismatch(chatPrompt)) { message('Cancel the calibration with the incorrect rack selection before starting a corrected plan.'); return; }
      if (chatPrompt && chatPrompt.source === 'touchscreen') {
        document.querySelector('#chat-hamilton-instruction button').click(); return;
      }
      api('respond',{prompt_id:promptId,response:'Ok',ready:true}).then(refresh).catch(function (e) { message(e.message); });
    };
    refresh(); setInterval(refresh,2500);
  });
}());
