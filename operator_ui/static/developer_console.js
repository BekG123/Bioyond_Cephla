/* Preserve proven controls; organize them and add a read-only DSL workbench. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const right = $('right');
  const essentials = new Set(['Connection & state', 'Jog', 'Gripper (E1) — 28 = open']);
  const legacy = document.createElement('details');
  legacy.className = 'dev-legacy'; legacy.id = 'dev-legacy';
  const summary = document.createElement('summary');
  summary.textContent = 'Legacy tools'; legacy.appendChild(summary);
  const extraNav = document.createElement('div'); extraNav.className = 'dev-extra-nav';
  for (const id of ['tabbtn-points', 'tabbtn-transfer', 'tabbtn-depth']) extraNav.appendChild($(id));
  legacy.appendChild(extraNav);

  // Move the actual key inputs, preserving their listeners and credential storage.
  const connection = document.createElement('details'); connection.className = 'card';
  connection.id = 'dev-api-settings';
  const connectionTitle = document.createElement('summary'); connectionTitle.textContent = 'API settings';
  connection.appendChild(connectionTitle);
  connection.appendChild($('imitation-key').closest('.row'));
  connection.appendChild($('imitation-dev-status'));
  connection.appendChild($('agent-settings'));

  for (const card of [...right.children]) {
    const title = card.querySelector('h2')?.textContent.trim();
    if (!essentials.has(title) && card.id !== 'envcard') legacy.appendChild(card);
  }
  // Envelope configuration remains available but no longer dominates the screen.
  const envelope = $('envcard');
  const limits = document.createElement('details'); limits.id = 'dev-limits';
  const limitsTitle = document.createElement('summary'); limitsTitle.textContent = 'Workspace limits';
  limits.appendChild(limitsTitle); envelope.replaceWith(limits); limits.appendChild(envelope);
  const calibration = document.createElement('div'); calibration.className = 'card';
  calibration.id = 'dev-calibration';
  const calibrationTitle = document.createElement('h2'); calibrationTitle.textContent = 'Calibration';
  const calibrationButtons = document.createElement('div'); calibrationButtons.className = 'row';
  for (const id of ['calibrate-two-disk', 'calibrate-48well']) calibrationButtons.appendChild(legacy.querySelector('#' + id));
  calibration.append(calibrationTitle, calibrationButtons);
  right.append(calibration, connection, legacy);

  const stopRow = document.createElement('div'); stopRow.className = 'dev-stop-row';
  for (const [label, action] of [
    ['Stop sequence', () => api('/seq/stop', {})],
    ['Stop program', () => api('/program', {action:'stop'})],
    ['Debugger', () => showTab('dsl')],
  ]) {
    const button = document.createElement('button'); button.textContent = label;
    button.className = label.startsWith('Stop') ? 'stop' : 'ghost'; button.onclick = action;
    stopRow.appendChild(button);
  }
  $('left').insertBefore(stopRow, $('campanel'));

  let failure = null, example = '', initialized = false, loading = false, editingVersion = 0;
  let devinAvailable = false, devinBusy = false, devinTimer = null;
  function updateDevinButton() {
    $('dsl-devin').disabled = !devinAvailable || devinBusy || !failure;
    $('dsl-devin-repair').disabled = !devinAvailable || devinBusy || !failure;
  }
  async function refreshDevin() {
    clearTimeout(devinTimer);
    try {
      const data = await request('devin');
      devinAvailable = data.available;
      devinBusy = data.job?.state === 'running';
      $('dsl-devin-auto').checked = !!data.auto_repair;
      $('dsl-devin-setup').textContent = `${data.setup} Review workspace: ${data.workspace}`;
      const job = data.job;
      $('dsl-devin-status').textContent = job
        ? `Review ${job.id.slice(0,8)} · ${job.state}. ${job.error || ''}` +
          (job.failure_id !== failure?.id ? ' This review belongs to a different recorded failure.' : '') +
          (job.source !== $('dsl-editor').value ? ' The current draft differs from the submitted draft.' : '')
        : (data.available ? 'Ready' : 'CLI unavailable · See Settings');
      $('dsl-devin-output').textContent = job?.response
        ? 'Unreviewed · Not applied\n\n' + job.response
        : (devinBusy ? 'Running…' : 'No proposal.');
      if (data.deferred_failure) $('dsl-devin-status').textContent += ` Deferred: ${data.deferred_failure.error}`;
      const branch = $('dsl-devin-branch');
      branch.hidden = !job?.remote_verified;
      if (job?.remote_verified) { branch.href = job.branch_url; branch.textContent = `${job.branch} · ${job.commit.slice(0,8)}`; }
      if (devinBusy || data.auto_repair) devinTimer = setTimeout(refreshDevin, 2000);
    } catch (error) {
      $('dsl-devin-status').textContent = error.message + ' Use Refresh Devin status to reconnect; do not resubmit an uncertain job.';
      devinAvailable = false;
    }
    updateDevinButton();
  }
  const storageKey = 'cephla.developer.dsl.v1';
  const status = (text, error=false) => {
    $('dsl-status').textContent = text; $('dsl-status').dataset.error = String(error);
  };
  async function request(path, data) {
    const response = await fetch('/developer/api/dsl/' + path, data === undefined ? {cache:'no-store'} : {
      method:'POST', headers:{'Content-Type':'application/json','X-Cephla-View':'developer'}, body:JSON.stringify(data)
    });
    const value = await response.json();
    if (!response.ok || !value.ok) throw new Error(value.error || 'Diagnostic request failed.');
    return value;
  }
  function invalidatePreview() {
    editingVersion += 1;
    $('dsl-python').textContent = 'Draft changed. Recompile.';
    $('dsl-roundtrip').textContent = 'Draft changed. Recompile.';
  }
  async function refresh() {
    if (loading) return;
    loading = true;
    try {
      const data = await request('diagnostic');
      const changed = failure?.id !== data.failure?.id;
      failure = data.failure; example = data.example;
      if (!initialized) {
        try { $('dsl-editor').value = localStorage.getItem(storageKey) || ''; } catch (_) {}
        initialized = true;
      }
      if (changed) { $('dsl-agent-output').hidden = true; $('dsl-agent-output').textContent = ''; }
      $('dsl-agent').disabled = !failure || !data.model_ready;
      $('dsl-error').textContent = failure ? failure.error : 'No recorded failure.';
      const location = failure?.evidence?.location;
      $('dsl-location').textContent = location ? `${location.path}:${location.line} · ${location.function}` : 'Source location unavailable';
      $('dsl-provenance').textContent = failure ? `${failure.at} · ${failure.sequence || 'sequence'} · run ${failure.run_id || 'not recorded'}` : '';
      const evidence = failure?.evidence;
      $('dsl-source').textContent = evidence?.source ? evidence.source.split('\n').map((line,i) => `${evidence.source_start_line+i}  ${line}`).join('\n') : 'No captured traceback.';
      $('dsl-explanation').textContent = failure?.dsl
        ? failure.dsl.split('\n').filter(line => !line.startsWith('# Source explanation only') && !line.startsWith('# Python expressions retained')).join('\n')
        : 'Unavailable.';
      status(failure ? 'Failure loaded' : 'Ready');
      refreshDevin();
    } catch (error) { status(error.message, true); }
    finally { loading = false; }
  }
  $('dsl-refresh').onclick = refresh;
  $('dsl-example').onclick = async () => {
    if (!example) await refresh();
    if (!example) return;
    if ($('dsl-editor').value.trim() && !confirm('Replace your current draft with the parking example?')) return;
    $('dsl-editor').value = example; $('dsl-editor').dispatchEvent(new Event('input'));
    status('Example loaded');
  };
  $('dsl-editor').addEventListener('input', () => {
    invalidatePreview();
    updateDevinButton();
    try { localStorage.setItem(storageKey, $('dsl-editor').value); } catch (_) {}
  });
  $('dsl-editor').addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    event.preventDefault();
    const editor = event.target;
    editor.setRangeText('    ', editor.selectionStart, editor.selectionEnd, 'end');
    editor.dispatchEvent(new Event('input'));
  });
  $('dsl-translate').onclick = async () => {
    const version = editingVersion;
    $('dsl-translate').disabled = true;
    try {
      const value = await request('translate', {source:$('dsl-editor').value});
      if (version !== editingVersion) { status('Draft changed. Recompile.'); return; }
      $('dsl-python').textContent = value.python;
      $('dsl-roundtrip').textContent = value.roundtrip_dsl;
      $('dsl-note').textContent = value.note;
      status('Compiled · Preview only');
    } catch (error) { invalidatePreview(); status(error.message, true); }
    finally { $('dsl-translate').disabled = false; }
  };
  $('dsl-agent').onclick = async () => {
    if (!failure) return;
    const id = failure.id; $('dsl-agent').disabled = true;
    status('Analyzing…');
    try {
      const value = await request('explain', {failure_id:id});
      if (failure?.id !== id) { status('A different failure is selected. Refresh its explanation.'); return; }
      $('dsl-agent-output').textContent = 'Unreviewed\n\n' + value.explanation;
      $('dsl-agent-output').hidden = false;
      status('Analysis complete');
    } catch (error) { status(error.message, true); }
    finally { $('dsl-agent').disabled = false; }
  };
  window.DeveloperConsole = {refresh};
  $('dsl-devin-refresh').onclick = refreshDevin;
  async function submitDevin(mode) {
    if (!failure || devinBusy) return;
    devinBusy = true; updateDevinButton();
    $('dsl-devin-status').textContent = 'Submitting…';
    try {
      await request('devin', {failure_id:failure.id, source:$('dsl-editor').value, mode});
      await refreshDevin();
    } catch (error) {
      // An uncertain network response may hide a successfully started job.
      await refreshDevin();
      $('dsl-devin-status').textContent = error.message + ' Check review status before trying again.';
    }
  }
  $('dsl-devin').onclick = () => submitDevin('review');
  $('dsl-devin-repair').onclick = () => submitDevin('repair');
  $('dsl-devin-auto').onchange = async event => {
    const control = event.target; control.disabled = true;
    try { await request('devin/settings', {auto_repair:control.checked}); await refreshDevin(); }
    catch (error) { control.checked = !control.checked; $('dsl-devin-status').textContent = error.message; }
    finally { control.disabled = false; }
  };
  refresh();
})();
