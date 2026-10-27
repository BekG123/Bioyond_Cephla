/* Preserve proven controls; organize them and add a read-only DSL workbench. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const right = $('right');
  const essentials = new Set(['Connection & state', 'Jog', 'Gripper (E1) — 28 = open']);
  const legacy = document.createElement('details');
  legacy.className = 'dev-legacy'; legacy.id = 'dev-legacy';
  const summary = document.createElement('summary');
  summary.textContent = 'Older tools and experiments'; legacy.appendChild(summary);
  const note = document.createElement('p'); note.className = 'lbl';
  note.textContent = 'Previous calibration, teaching and analysis tools remain here for reference.';
  legacy.appendChild(note);
  const extraNav = document.createElement('div'); extraNav.className = 'dev-extra-nav';
  for (const id of ['tabbtn-points', 'tabbtn-transfer', 'tabbtn-depth']) extraNav.appendChild($(id));
  legacy.appendChild(extraNav);

  // Move the actual key inputs, preserving their listeners and credential storage.
  const connection = document.createElement('details'); connection.className = 'card';
  connection.id = 'dev-api-settings';
  const connectionTitle = document.createElement('summary'); connectionTitle.textContent = 'API connection settings';
  connection.appendChild(connectionTitle);
  const explanation = document.createElement('p'); explanation.className = 'dev-key-note';
  explanation.textContent = 'Shared model connection for Lacry and developer explanations. Keys stay in the existing credential store.';
  connection.appendChild(explanation);
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
  right.append(connection, legacy);

  const stopRow = document.createElement('div'); stopRow.className = 'dev-stop-row';
  for (const [label, action] of [
    ['Stop sequence', () => api('/seq/stop', {})],
    ['Stop program', () => api('/program', {action:'stop'})],
    ['Inspect last failure', () => showTab('dsl')],
  ]) {
    const button = document.createElement('button'); button.textContent = label;
    button.className = label.startsWith('Stop') ? 'stop' : 'ghost'; button.onclick = action;
    stopRow.appendChild(button);
  }
  $('left').insertBefore(stopRow, $('campanel'));

  let failure = null, example = '', initialized = false, loading = false, editingVersion = 0;
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
    $('dsl-python').textContent = 'Draft changed. Translate again to update this preview.';
    $('dsl-roundtrip').textContent = 'Waiting for translation of the current draft.';
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
      $('dsl-error').textContent = failure ? failure.error : 'No failure has been recorded by this inspector.';
      const location = failure?.evidence?.location;
      $('dsl-location').textContent = location ? `${location.path}:${location.line} · ${location.function}` : 'Source location unavailable';
      $('dsl-provenance').textContent = failure ? `${failure.at} · ${failure.sequence || 'sequence'} · run ${failure.run_id || 'not recorded'}` : 'New sequence exceptions will include a captured source location.';
      const evidence = failure?.evidence;
      $('dsl-source').textContent = evidence?.source ? evidence.source.split('\n').map((line,i) => `${evidence.source_start_line+i}  ${line}`).join('\n') : 'No traceback was stored for this failure. A source location will not be guessed.';
      $('dsl-explanation').textContent = failure?.dsl || 'No source explanation yet.';
      status(failure ? 'Evidence loaded. Source explanations and draft fixes are separate.' : 'Ready. Load the parking example to try your DSL.');
    } catch (error) { status(error.message, true); }
    finally { loading = false; }
  }
  $('dsl-refresh').onclick = refresh;
  $('dsl-example').onclick = async () => {
    if (!example) await refresh();
    if (!example) return;
    if ($('dsl-editor').value.trim() && !confirm('Replace your current draft with the parking example?')) return;
    $('dsl-editor').value = example; $('dsl-editor').dispatchEvent(new Event('input'));
    status('Example loaded. The 120-check budget is illustrative, not a live timeout setting.');
  };
  $('dsl-editor').addEventListener('input', () => {
    invalidatePreview();
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
      if (version !== editingVersion) { status('Draft changed during translation. Translate the current draft again.'); return; }
      $('dsl-python').textContent = value.python;
      $('dsl-roundtrip').textContent = value.roundtrip_dsl;
      $('dsl-note').textContent = value.note;
      status('Translation complete. Python and reconstructed DSL are previews only.');
    } catch (error) { invalidatePreview(); status(error.message, true); }
    finally { $('dsl-translate').disabled = false; }
  };
  $('dsl-agent').onclick = async () => {
    if (!failure) return;
    const id = failure.id; $('dsl-agent').disabled = true;
    status('Generating an explanation from the recorded evidence…');
    try {
      const value = await request('explain', {failure_id:id});
      if (failure?.id !== id) { status('A different failure is selected. Refresh its explanation.'); return; }
      $('dsl-agent-output').textContent = 'MODEL DRAFT · Requires developer review\n\n' + value.explanation;
      $('dsl-agent-output').hidden = false;
      status('Agent explanation ready. It has not changed code or run hardware.');
    } catch (error) { status(error.message, true); }
    finally { $('dsl-agent').disabled = false; }
  };
  window.DeveloperConsole = {refresh};
  refresh();
})();
