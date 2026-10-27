/* Lacry workspace client.
   Polls state, renders tiles / conversation / plans, and never sends a motion
   request on its own: a tile only asks for a PLAN, which the researcher then
   confirms. */
(function () {
  'use strict';

  var el = function (id) { return document.getElementById(id); };
  var all = function (sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); };
  var state = { planId: null, planExecutable: true, reviewId: null, lastTranscript: -1, sending: false };

  function post(path, body) {
    return fetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {})
    }).then(function (response) {
      return response.json().catch(function () { return { ok: false, message: 'The console did not answer.' }; })
        .then(function (data) {
          if (!response.ok && data.ok !== true) {
            throw new Error(data.message || data.error || ('Request failed (' + response.status + ')'));
          }
          return data;
        });
    });
  }
  function get(path) { return fetch(path, { headers: { Accept: 'application/json' } }).then(function (r) { return r.json(); }); }

  function alertBox(message, good) {
    var box = el('alert');
    if (!message) { box.hidden = true; return; }
    box.hidden = false;
    box.className = 'notice ' + (good ? 'good' : 'bad');
    box.textContent = message;
  }

  /* ----------------------------------------------------------- transcript */
  // Small, local Markdown renderer. Message content is always text nodes:
  // no model-provided HTML, attributes, links or scripts are ever executed.
  function inlineText(parent, value) {
    var tokens = /`([^`\n]+)`|\*\*([^*\n]+)\*\*|__([^_\n]+)__|\*([^*\n]+)\*/g;
    var match, offset = 0;
    while ((match = tokens.exec(value))) {
      parent.appendChild(document.createTextNode(value.slice(offset, match.index)));
      var content = match[1] || match[2] || match[3] || match[4];
      if (match[4] && content.trim() !== content) {
        parent.appendChild(document.createTextNode(match[0]));
      } else {
        var node = document.createElement(match[1] ? 'code' : (match[4] ? 'em' : 'strong'));
        node.textContent = content;
        parent.appendChild(node);
      }
      offset = tokens.lastIndex;
    }
    parent.appendChild(document.createTextNode(value.slice(offset)));
  }

  function messageContent(parent, value) {
    var paragraph = null, lists = [], code = null;
    String(value || '').replace(/\r\n?/g, '\n').split('\n').forEach(function (line) {
      if (/^\s*```/.test(line)) {
        paragraph = null; lists = [];
        if (code) { code = null; }
        else {
          var pre = document.createElement('pre');
          code = document.createElement('code'); pre.appendChild(code); parent.appendChild(pre);
        }
        return;
      }
      if (code) { code.appendChild(document.createTextNode(line + '\n')); return; }
      if (!line.trim()) { paragraph = null; lists = []; return; }
      var bullet = /^(\s*)(?:([-*+•])|(\d+)[.)])\s+(.+)$/.exec(line);
      if (bullet) {
        paragraph = null;
        var indent = bullet[1].replace(/\t/g, '    ').length;
        var type = bullet[3] ? 'ol' : 'ul';
        while (lists.length && indent < lists[lists.length - 1].indent) { lists.pop(); }
        if (lists.length && indent === lists[lists.length - 1].indent &&
            type !== lists[lists.length - 1].type) { lists.pop(); }
        if (!lists.length || indent > lists[lists.length - 1].indent) {
          var list = document.createElement(type);
          if (type === 'ol') { list.start = Number(bullet[3]); }
          var target = lists.length ? lists[lists.length - 1].item : parent;
          target.appendChild(list);
          lists.push({ indent: indent, type: type, node: list, item: null });
        }
        var entry = document.createElement('li');
        inlineText(entry, bullet[4]);
        lists[lists.length - 1].node.appendChild(entry);
        lists[lists.length - 1].item = entry;
        return;
      }
      // Indented wrapped text belongs to the preceding list item.
      if (lists.length && /^\s+/.test(line)) {
        var item = lists[lists.length - 1].item;
        item.appendChild(document.createTextNode(' ')); inlineText(item, line.trim()); return;
      }
      lists = [];
      var heading = /^#{1,6}\s+(.+)$/.exec(line);
      if (heading) {
        paragraph = null;
        var title = document.createElement('p'); title.className = 'message-heading';
        inlineText(title, heading[1]); parent.appendChild(title); return;
      }
      if (!paragraph) { paragraph = document.createElement('p'); parent.appendChild(paragraph); }
      else { paragraph.appendChild(document.createElement('br')); }
      inlineText(paragraph, line);
    });
  }

  var MARK = '<svg width="18" height="18" viewBox="0 0 38 38" aria-hidden="true">' +
    '<circle cx="19" cy="19" r="13.5" fill="none" stroke="#2FC2F0" stroke-width="1.6" stroke-opacity=".4" stroke-dasharray="3 6"></circle>' +
    '<circle cx="16.5" cy="21.5" r="6.2" fill="#2FC2F0" fill-opacity=".16"></circle>' +
    '<path d="M16 22 C 20 20, 24 17, 25.5 13.5" fill="none" stroke="#0B5E78" stroke-width="2.4" stroke-linecap="round"></path>' +
    '<circle cx="25.8" cy="13" r="2.6" fill="#0B5E78"></circle></svg>';

  function renderTranscript(items) {
    var signature = JSON.stringify(items);
    if (signature === state.lastTranscript) { return; }
    state.lastTranscript = signature;
    var log = el('chat-log');
    var atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 70;
    log.textContent = '';
    if (!items.length) {
      var hello = document.createElement('div');
      hello.className = 'msg lacry';
      hello.innerHTML = MARK + '<div><div class="who">Lacry</div><div class="bubble">' +
        'How can I help in the lab? Tell me what you’d like to do.</div></div>';
      log.appendChild(hello);
    }
    items.forEach(function (item) {
      var row = document.createElement('div');
      row.className = 'msg ' + (item.role === 'researcher' ? 'researcher' : 'lacry');
      if (item.role !== 'researcher') { row.innerHTML = MARK; }
      var wrap = document.createElement('div');
      var who = document.createElement('div');
      who.className = 'who';
      who.textContent = item.role === 'researcher' ? 'You' : 'Lacry';
      var text = document.createElement('div');
      text.className = 'bubble';
      if (item.role === 'researcher') { text.textContent = item.text; }
      else { messageContent(text, item.text); }
      wrap.appendChild(who); wrap.appendChild(text); row.appendChild(wrap);
      log.appendChild(row);
    });
    if (atBottom) { log.scrollTop = log.scrollHeight; }
  }

  /* ----------------------------------------------------------------- plan */
  function renderPlan(plan) {
    // The host presents the plan and requirements in chat. A human reply starts
    // that exact pending plan; there is no separate confirmation panel.
    state.planId = plan ? plan.id : null;
    var log = el('chat-log'), old = el('chat-plan-answer');
    var allowed = plan && plan.executable !== false && !(state.lacryRunning || state.lacryBusy);
    if (!allowed) { if (old) { old.remove(); } return; }
    if (old && old.dataset.planId === plan.id) { return; }
    if (old) { old.remove(); }
    var row = document.createElement('div');
    row.id = 'chat-plan-answer'; row.className = 'chat-plan-answer'; row.dataset.planId = plan.id;
    row.setAttribute('role','group'); row.setAttribute('aria-label','Confirm the displayed plan');
    ['Yes','No'].forEach(function (answer) {
      var button = document.createElement('button'), face = document.createElement('span');
      button.type='button'; button.className='control-button chat-answer';
      button.disabled=!!state.answering;
      face.className='control-face'; face.textContent=answer; button.appendChild(face);
      button.setAttribute('aria-label',answer === 'Yes' ? 'Yes, start this plan' : 'No, cancel this plan');
      button.addEventListener('click',function () {
        if (state.answering || state.planId !== plan.id) { return; }
        state.answering=true;
        row.querySelectorAll('button').forEach(function (b) { b.disabled=true; });
        post('/researcher/api/lacry/' + (answer === 'Yes' ? 'confirm' : 'cancel'),
             {plan_id:plan.id,ready:answer === 'Yes'})
          .then(function (data) { if (data.ok === false) { throw new Error(data.message || data.error || 'The plan did not start.'); } })
          .catch(function (error) { alertBox(error.message); })
          .finally(function () { state.answering=false; row.remove(); poll(); });
      });
      row.appendChild(button);
    });
    log.appendChild(row); log.scrollTop=log.scrollHeight;
  }

  function renderReview(review) {
    var card = el('review');
    if (!review) { card.hidden = true; state.reviewId = null; return; }
    state.reviewId = review.id;
    el('review-label').textContent = review.label;
    card.hidden = false;
  }

  function renderRunning(running, experiment) {
    var card = el('running');
    var active = running && running.active;
    card.hidden = !running || (!active && running.ok == null);
    document.body.classList.toggle('running', !!active);
    if (card.hidden) { return; }
    el('running-title').textContent = active ? 'Running' : (running.ok ? 'Completed' : 'Stopped');
    card.dataset.outcome = active ? 'active' : (running.ok ? 'complete' : 'stopped');
    var done = running.done || [];
    el('running-count').textContent = experiment && experiment.repetitions > 1 ?
      (experiment.completed_cycles || 0) + ' / ' + experiment.repetitions + ' cycles' :
      done.length + ' steps complete';
    el('running-message').textContent = running.message || '';
    var list = el('running-steps'); list.textContent = '';
    done.forEach(function (label) {
      var li = document.createElement('li'); li.className = 'done'; li.textContent = label + ' — done'; list.appendChild(li);
    });
    if (running.step && (active || !running.ok)) {
      var now = document.createElement('li'); now.className = 'now'; now.textContent = running.step; list.appendChild(now);
    }
  }

  function renderActivity(items) {
    var list = el('activity'); list.textContent = '';
    if (!items || !items.length) {
      var empty = document.createElement('li'); empty.className = 'empty';
      empty.textContent = 'Nothing run yet in this session.'; list.appendChild(empty); return;
    }
    items.forEach(function (item) {
      var li = document.createElement('li');
      var when = document.createElement('time');
      when.textContent = (item.at || '').slice(11, 16) + ' ';
      li.appendChild(when); li.appendChild(document.createTextNode(item.line));
      list.appendChild(li);
    });
  }

  function renderExperiments(lacry) {
    var rows = [], run = lacry && lacry.running || {}, pending = lacry && lacry.pending;
    var meta = lacry && lacry.experiment || {};
    if (!lacry || lacry.ok === false) {
      rows.push({name:'Experiment status', badge:'Connection lost', tone:'attention',
        detail:'Live updates are unavailable. Check the console connection.', value:null});
    } else {
      if (run.active || run.ok != null) {
        var count = (run.done || []).length;
        var total = Number.isInteger(meta.total_steps) && meta.total_steps > 0 ? meta.total_steps : null;
        var waiting = run.active && lacry.review;
        var complete = !run.active && run.ok === true;
        var stopped = !run.active && run.ok === false;
        rows.push({name:meta.name || 'Lab workflow',
          badge:waiting ? 'Waiting for you' : run.active ? 'Running' : complete ? 'Completed' : 'Stopped',
          tone:waiting ? 'attention' : stopped ? 'failed' : complete ? 'complete' : 'active',
          detail:waiting ? lacry.review.label : stopped ? (run.error || run.message || 'Check the stopped step.')
            : (run.step || run.message || 'Workflow complete.'),
          count:(meta.repetitions > 1 ? (meta.completed_cycles || 0)+' of '+meta.repetitions+' cycles complete · ' : '')+
            (total ? Math.min(count,total)+' of '+total+' steps complete' : complete ? 'Finished' : 'Live activity'),
          value:complete ? 100 : total ? Math.min(99,Math.floor(count*100/total)) : null});
      }
      if (pending && !run.active) {
        var preview = pending.executable === false;
        rows.push({name:(pending.labels || []).join(', ') || 'Next experiment',
          badge:preview ? 'Preview only' : 'Awaiting confirmation', tone:'attention',
          detail:preview ? (pending.blockers || []).join(' ') : pending.summary || 'Review the plan in chat.',
          count:preview ? 'Not started' : 'Confirm the plan in chat to start', value:0});
      }
      var squid = lacry.links && lacry.links.squid, job = squid && squid.job;
      if (job || (squid && ['running','finishing','unknown','failed','aborted'].indexOf(squid.status) >= 0)) {
        var verified = squid.connected && squid.completion_confirmed === true && squid.status === 'completed';
        var active = squid.connected && ['running','finishing'].indexOf(squid.status) >= 0;
        rows.push({name:(squid.camera_simulated && squid.stage_simulated === false ?
          'Squid · real stage · simulated camera' : squid.simulation ? 'Squid · mock imaging' : 'Squid imaging'),
          badge:!squid.connected ? 'Connection lost' : verified ? 'Completed' :
            ({running:'Imaging',finishing:'Finishing',historical:'Previous run',aborted:'Cancelled',
              failed:'Failed',unknown:'Needs attention'}[squid.status] || 'Status unverified'),
          tone:verified ? 'complete' : active ? 'active' : 'attention',
          detail:job && job.experiment_id || squid.message || 'Checking imaging status.',
          count:verified && job && job.stats ? job.stats.total_images+(squid.simulation ? ' simulated images' : ' images captured') : squid.message || '',
          value:verified ? 100 : null});
      }
    }
    var signature = JSON.stringify(rows);
    if (signature === state.experimentSignature) { return; }
    state.experimentSignature = signature;
    var box = el('experiment-bars'); box.textContent = '';
    if (!rows.length) {
      var empty = document.createElement('p'); empty.className = 'experiment-empty';
      empty.textContent = 'No experiment running. Choose a routine or ask Lacry to plan one.';
      box.appendChild(empty); return;
    }
    rows.forEach(function (item) {
      var row = document.createElement('article'); row.className = 'experiment-row '+item.tone;
      var head = document.createElement('div'); head.className = 'experiment-row-head';
      var title = document.createElement('strong'); title.textContent = item.name;
      var badge = document.createElement('span'); badge.className = 'experiment-badge'; badge.textContent = item.badge;
      head.append(title,badge);
      var detail = document.createElement('p'); detail.className = 'experiment-detail'; detail.textContent = item.detail;
      var track = document.createElement('div'); track.className = 'experiment-track';
      track.setAttribute('role','progressbar'); track.setAttribute('aria-label',item.name+' progress');
      track.setAttribute('aria-valuemin','0'); track.setAttribute('aria-valuemax','100');
      track.setAttribute('aria-valuetext',item.badge+(item.count ? ': '+item.count : ''));
      var fill = document.createElement('span');
      if (item.value != null) {
        track.setAttribute('aria-valuenow',String(item.value)); fill.style.width = item.value+'%';
      } else { track.classList.add(item.tone === 'active' ? 'indeterminate' : 'unavailable'); }
      track.appendChild(fill);
      var caption = document.createElement('div'); caption.className = 'experiment-caption'; caption.textContent = item.count || item.badge;
      row.append(head,detail,track,caption); box.appendChild(row);
    });
  }

  /* --------------------------------------------------------------- tiles */
  function setTileState(key, text, kind) {
    all('[data-state="' + key + '"]').forEach(function (node) { node.textContent = text; });
    all('[data-dot="' + key + '"]').forEach(function (node) { node.className = 'dot' + (kind ? ' ' + kind : ''); });
  }

  function renderLinks(links, hand) {
    if (links) {
      ['hamilton', 'squid', 'arm'].forEach(function (name) {
        var link = links[name] || {};
        var label = link.connected ? 'connected' : 'disconnected';
        if (name === 'hamilton') {
          var wasPaused = hamiltonCameraPaused;
          hamiltonCameraPaused = !!(link.polling && link.polling.camera_paused);
          if (activeCam === 'hamilton' && wasPaused !== hamiltonCameraPaused) {
            clearCameraRequest(); refreshCamera();
          }
          label = !link.connected ? 'disconnected' : link.global_state !== 'Idle' ? (link.global_state || 'connected') : link.initialized ? 'ready' : 'needs initialization';
          el('hamilton-help').textContent = (link.message || 'Hamilton controls') + ' Click to open the Hamilton panel.';
        }
        if (name === 'squid') {
          label = link.connected ? 'connected' : 'disconnected';
          el('squid-help').textContent = (link.message || 'Connect Lacry to Squid to follow imaging progress and completion.') +
            ' Ask Lacry to calibrate, deliver the plate, run the selected imaging setup and wait for completion.';
        }
        setTileState(name, label, link.connected ? (name !== 'squid' && link.status === 'running' ? 'busy' : 'ok') : '');
        all('[data-link="' + name + '"]').forEach(function (tile) {
          tile.classList.toggle('linked', !!link.connected);
        });
      });
    }

  }

  function renderStatus(lacry, status) {
    var dot = el('state-dot'), label = el('state-label');
    var robot = (status && status.robot) || 'Checking…';
    var hand = status && status.hand_guiding ? status.hand_guiding.state : null;
    var thinking = !!(lacry && lacry.busy);
    var running = !!(lacry && lacry.running && lacry.running.active);
    all('[data-action]').forEach(function (button) { button.disabled = running; });


    document.body.classList.toggle('thinking', thinking);
    if (thinking) { dot.className = 'dot busy'; label.textContent = 'Lacry is thinking'; }
    else if (running) { dot.className = 'dot busy'; label.textContent = 'Running'; }
    else if (hand === 'active') { dot.className = 'dot busy'; label.textContent = 'Hand-guiding'; }
    else if (status && status.connected) { dot.className = 'dot ok'; label.textContent = robot; }
    else { dot.className = 'dot bad'; label.textContent = robot; }

    el('connect-button').hidden = !(status && status.connected === false);
    if (activeCam === 'eye') {
      el('cam-state').textContent = status && status.camera ? status.camera.toLowerCase() : 'checking…';
    } else {
      el('cam-state').textContent = cameraViewState;
    }
    el('chat-send').disabled = thinking || state.sending;
    el('chat-input').disabled = thinking || state.sending;
    el('chat-hint').textContent = thinking || state.sending ? 'Thinking…' : 'Your lab assistant';
    el('chat-input').placeholder = 'Message Lacry…';
    if (lacry && lacry.configured === false) {
      el('chat-hint').textContent = 'API key needed';
      el('chat-input').placeholder = 'Connect Lacry in Developer view';
    }
    renderLinks(lacry && lacry.links, hand);
  }

  /* --------------------------------------------------------------- camera */
  /* Refresh only the selected camera, with at most one frame in flight. */
  var CAMERAS = {
    eye: { label: 'Eye-in-hand', src: '/frame',
           note: 'CAMERA VIEW<br>waiting for the eye-in-hand camera' },
    hamilton: { label: 'Inside Hamilton', src: '/researcher/api/lacry/hamilton/camera',
           note: 'INSIDE HAMILTON<br>connecting to the deck camera' },
    squid: { label: 'Squid', src: null,
           note: 'SQUID<br>no camera is connected to this console yet' }
  };
  var activeCam = 'eye';
  var camFailures = 0;
  var cameraViewState = 'connecting…';
  var cameraRequest = null;
  var cameraLiveTimer = null;
  var hamiltonCameraPaused = false;

  function setCameraLive(live) {
    clearTimeout(cameraLiveTimer);
    el('cam-live').hidden = !live;
    if (live) { cameraLiveTimer = setTimeout(function () { setCameraLive(false); }, 6000); }
  }

  function renderQuestion(question) {
    var old=el('chat-question-answer');
    state.questionId=question ? question.id : null;
    var options=question && Array.isArray(question.options) ? question.options : [];
    var yesNo=options.length===2 && options.some(function (x) { return /^yes$/i.test(x.trim()); }) &&
      options.some(function (x) { return /^no$/i.test(x.trim()); });
    if (!yesNo || state.planId || state.lacryRunning || state.lacryBusy) {
      if (old) { old.remove(); } return;
    }
    if (old && old.dataset.questionId===question.id) { return; }
    if (old) { old.remove(); }
    var row=document.createElement('div'); row.id='chat-question-answer';
    row.className='chat-plan-answer'; row.dataset.questionId=question.id;
    row.setAttribute('role','group'); row.setAttribute('aria-label','Answer Lacry’s question');
    function answer(value) {
      if (state.answering || state.sending || state.questionId!==question.id || !value.trim()) { return; }
      state.answering=true;
      row.querySelectorAll('button,input').forEach(function (x) { x.disabled=true; });
      post('/researcher/api/lacry/question/answer',{question_id:question.id,answer:value.trim()})
        .then(function (data) { if (data.ok===false) { throw new Error(data.message || data.error || 'The answer could not be sent.'); } })
        .catch(function (error) { alertBox(error.message); })
        .finally(function () { state.answering=false; row.remove(); poll(); });
    }
    function button(label,click) {
      var b=document.createElement('button'),face=document.createElement('span');
      b.type='button';b.className='control-button chat-answer';b.disabled=!!state.answering;
      face.className='control-face';face.textContent=label;b.appendChild(face);
      b.addEventListener('click',click);row.appendChild(b);
    }
    ['Yes','No'].forEach(function (label) { button(label,function () { answer(label); }); });
    var log=el('chat-log');log.appendChild(row);log.scrollTop=log.scrollHeight;
  }

  function clearCameraRequest() {
    if (!cameraRequest) { return; }
    clearTimeout(cameraRequest.timer);
    cameraRequest.probe.onload = cameraRequest.probe.onerror = null;
    cameraRequest.probe.removeAttribute('src');
    cameraRequest = null;
  }

  function showPlaceholder(html) {
    setCameraLive(false);
    var image = el('cam-image'), placeholder = el('cam-placeholder');
    image.hidden = true;
    placeholder.style.display = 'flex';
    placeholder.innerHTML = html;
  }

  function selectCamera(name) {
    if (!CAMERAS[name]) { return; }
    clearCameraRequest();
    activeCam = name;
    camFailures = 0;
    cameraViewState = CAMERAS[name].src ? 'connecting…' : 'not connected';
    el('cam-state').textContent = cameraViewState;
    el('cam-name').textContent = CAMERAS[name].label;
    all('.cam-tab').forEach(function (tab) {
      var on = tab.dataset.cam === name;
      tab.classList.toggle('active', on);
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    el('cam-image').removeAttribute('src');
    showPlaceholder(CAMERAS[name].note);
    refreshCamera();
  }

  function refreshCamera() {
    var camera = CAMERAS[activeCam];
    if (activeCam === 'hamilton' && hamiltonCameraPaused) {
      clearCameraRequest();
      cameraViewState = 'paused during calibration';
      el('cam-state').textContent = cameraViewState;
      showPlaceholder('INSIDE HAMILTON<br>Camera paused during calibration. Resumes automatically.');
      return;
    }
    if (!camera.src) {
      el('cam-state').textContent = 'not connected';
      showPlaceholder(camera.note);
      return;
    }
    if (cameraRequest || document.hidden) { return; }
    var want = activeCam;
    var probe = new Image();
    var request = {probe:probe,timer:null};
    cameraRequest = request;
    probe.onload = function () {
      if (want !== activeCam || cameraRequest !== request) { return; }
      clearTimeout(request.timer); cameraRequest = null;
      camFailures = 0;
      setCameraLive(!document.hidden);
      cameraViewState = 'live · updated ' + new Date().toLocaleTimeString();
      el('cam-state').textContent = cameraViewState;
      var image = el('cam-image');
      image.alt = camera.label + ' live view';
      image.src = probe.src; image.hidden = false;
      el('cam-placeholder').style.display = 'none';
    };
    probe.onerror = function () {
      if (want !== activeCam || cameraRequest !== request) { return; }
      clearCameraRequest();
      camFailures += 1;
      cameraViewState = 'camera unavailable · retrying';
      el('cam-state').textContent = cameraViewState;
      showPlaceholder(camera.label.toUpperCase() + '<br>no image right now · reconnecting');
    };
    request.timer = setTimeout(function () { if (cameraRequest === request) { probe.onerror(); } }, 10000);
    probe.src = camera.src + (camera.src.indexOf('?') < 0 ? '?' : '&') + 't=' + Date.now();
  }

  /* -------------------------------------------------------------- console
     The same runner snapshot the Developer view's log reads, rendered in the
     same dark readout. Only repaints when the log actually changes. */
  var lastLog = -1;
  function renderConsole(seq) {
    if (!seq) { return; }
    var meta = el('console-meta');
    meta.textContent = seq.active ? ('running: ' + (seq.name || 'sequence'))
                                  : ((seq.name ? seq.name + ' · ' : '') + (seq.state || 'idle'));
    var lines = seq.log || [];
    var signature = JSON.stringify([seq.name, seq.state, lines]);
    if (signature === lastLog) { return; }
    lastLog = signature;
    var body = el('console-body');
    var atBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
    body.textContent = '';
    if (!lines.length) {
      var idle = document.createElement('div');
      idle.className = 'toast';
      idle.textContent = '· no sequence has run yet';
      body.appendChild(idle);
      return;
    }
    lines.forEach(function (line) {
      var row = document.createElement('div');
      row.className = line.level || 'info';
      var stamp = document.createElement('span');
      stamp.className = 't';
      stamp.textContent = '[' + String(line.t === undefined ? '' : line.t.toFixed(1)).padStart(7) + '] ';
      row.appendChild(stamp);
      row.appendChild(document.createTextNode('· ' + line.msg));
      body.appendChild(row);
    });
    if (atBottom) { body.scrollTop = body.scrollHeight; }
  }

  /* ----------------------------------------------------------------- poll */
  function poll() {
    return Promise.all([
      get('/researcher/api/lacry/state').catch(function () { return null; }),
      get('/researcher/api/status').catch(function () { return null; }),
      get('/seq').catch(function () { return null; })
    ]).then(function (results) {
      var lacry = results[0], status = results[1];
      renderExperiments(lacry);
      renderConsole(results[2]);
      if (lacry && lacry.ok !== false) {
        state.lacryRunning=!!(lacry.running && lacry.running.active);
        state.lacryBusy=!!lacry.busy;
        renderTranscript(lacry.transcript || []);
        renderPlan(lacry.pending);
        renderQuestion(lacry.question);
        if (window.renderHamiltonInstruction) { window.renderHamiltonInstruction(); }
        renderReview(lacry.review);
        renderRunning(lacry.running, lacry.experiment);
        renderActivity(lacry.activity);
      }
      renderStatus(lacry, status);
    });
  }

  function propose(name) {
    alertBox('');
    post('/researcher/api/lacry/button/' + name, {}).then(poll)
      .catch(function (error) { alertBox(error.message); });
  }

  /* ----------------------------------------------------------------- init */
  document.addEventListener('DOMContentLoaded', function () {
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') {
        all('.control-cell').forEach(function (cell) { cell.classList.add('tooltip-dismissed'); });
      }
    });
    all('.control-cell').forEach(function (cell) {
      cell.addEventListener('mouseenter', function () { cell.classList.remove('tooltip-dismissed'); });
      cell.addEventListener('focusin', function () { cell.classList.remove('tooltip-dismissed'); });
      cell.addEventListener('mouseleave', function () { cell.classList.remove('tooltip-dismissed'); });
      cell.addEventListener('focusout', function (event) {
        if (!cell.contains(event.relatedTarget)) { cell.classList.remove('tooltip-dismissed'); }
      });
    });

    all('[data-action]').forEach(function (tile) {
      tile.addEventListener('click', function () {
        var action = tile.dataset.action;
        if (action === 'hand') { action = tile.dataset.mode || 'hand_start'; }
        propose(action);
      });
    });

    all('[data-link]').forEach(function (tile) {
      tile.addEventListener('click', function () {
        if (tile.dataset.link === 'hamilton') { window.openHamiltonPanel(); return; }
        alertBox('');
        post('/researcher/api/lacry/link/' + tile.dataset.link, {})
          .then(function (data) { alertBox(data.message, true); poll(); })
          .catch(function (error) { alertBox(error.message); poll(); });
      });
    });

    // Click the mark and Lacry gets cute for a moment.
    el('logo-button').addEventListener('click', function () {
      document.body.classList.remove('cute');
      void document.body.offsetWidth;          // restart the animation
      document.body.classList.add('cute');
      window.setTimeout(function () { document.body.classList.remove('cute'); }, 1700);
    });

    el('connect-button').addEventListener('click', function () {
      var button = el('connect-button');
      button.disabled = true; alertBox('');
      post('/researcher/api/connect', {})
        .then(function (data) { alertBox(data.message, true); poll(); })
        .catch(function (error) { alertBox(error.message); })
        .then(function () { button.disabled = false; });
    });

    el('stop-button').addEventListener('click', function () {
      alertBox('');
      post('/researcher/api/lacry/stop', {})
        .then(function (data) { alertBox(data.message, true); poll(); })
        .catch(function (error) { alertBox(error.message); });
    });

    el('review-yes').addEventListener('click', function () {
      post('/researcher/api/lacry/review', { review_id: state.reviewId, approved: true })
        .then(function (data) { alertBox(data.message, true); poll(); })
        .catch(function (error) { alertBox(error.message); });
    });

    el('review-no').addEventListener('click', function () {
      post('/researcher/api/lacry/review', { review_id: state.reviewId, approved: false })
        .then(function (data) { alertBox(data.message, true); poll(); })
        .catch(function (error) { alertBox(error.message); });
    });

    function resizeComposer() {
      var input = el('chat-input');
      input.style.height = 'auto';
      input.style.height = Math.min(180, Math.max(64, input.scrollHeight + 2)) + 'px';
    }
    el('chat-input').addEventListener('input', resizeComposer);
    el('chat-input').addEventListener('keydown', function (event) {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
        event.preventDefault();
        if (!el('chat-send').disabled) { el('composer').requestSubmit(el('chat-send')); }
      }
    });
    window.addEventListener('resize', resizeComposer);

    el('composer').addEventListener('submit', function (event) {
      event.preventDefault();
      if (state.sending || state.answering || el('chat-send').disabled) { return; }
      var input = el('chat-input');
      var message = input.value.trim();
      if (!message) { return; }
      state.sending = true;
      input.value = ''; resizeComposer(); alertBox(''); el('chat-send').disabled = true;
      var questionId=state.planId ? null : state.questionId;
      post(questionId ? '/researcher/api/lacry/question/answer' : '/researcher/api/lacry/chat',
        questionId ? { question_id: questionId, answer: message } : { message: message })
        .then(poll)
        .catch(function (error) { alertBox(error.message); if (!input.value) { input.value = message; resizeComposer(); } return poll(); })
        .then(function () { state.sending = false; el('chat-send').disabled = false; input.disabled = false; input.focus(); });
    });

    all('.cam-tab').forEach(function (tab) {
      tab.addEventListener('click', function () { selectCamera(tab.dataset.cam); });
    });
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { setCameraLive(false); }
      else { refreshCamera(); }
    });

    poll();
    refreshCamera();
    setInterval(poll, 2000);
    setInterval(refreshCamera, 1600);
  });
}());
