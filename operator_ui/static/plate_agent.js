/* Camera-only scene pipeline; model text is never executed. */
(() => {
  const el = id => document.getElementById(id);
  const status = text => { el('agent-status').textContent = text; };
  let busy = false, pinnedUntil = 0, previewSample = null;
  function notice(text) { pinnedUntil = Date.now() + 5000; status(text); }
  async function post(path, body) {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Request failed');
    return result;
  }
  async function send(mode = 'analyze') {
    if (busy) return;
    busy = true;
    try {
      await post('/agent/run', {mode, message:el('agent-message').value, session:el('agent-session').value});
      notice('Capturing a fresh image...');
    } catch (error) { notice(error.message); }
    finally { busy = false; }
  }
  el('agent-send').addEventListener('click', () => send());
  el('agent-message').addEventListener('keydown', event => {
    if (event.key === 'Enter') { event.preventDefault(); send(); }
  });
  el('agent-shortcuts').addEventListener('click', event => {
    const mode = event.target.dataset.mode;
    if (mode) send(mode);
  });
  el('agent-stop').addEventListener('click', async () => {
    try { await post('/seq/stop', {}); notice('Stop requested; current inference may finish first.'); }
    catch (error) { notice(error.message); }
  });
  el('agent-key-save').addEventListener('click', async () => {
    try {
      await post('/agent/settings', {api_key:el('agent-key').value});
      el('agent-key').value = '';
      el('agent-settings').open = false;
      notice('Haiku key configured.');
    } catch (error) { notice(error.message); }
  });
  async function poll() {
    try {
      const [agent, sequence] = await Promise.all([
        fetch('/agent/state', {cache:'no-store'}).then(r => { if (!r.ok) throw new Error(); return r.json(); }),
        fetch('/seq', {cache:'no-store'}).then(r => r.json())]);
      el('agent-stage').textContent = agent.stage;
      el('agent-model').textContent = agent.model || '';
      const disabled = busy || sequence.active;
      el('agent-send').disabled = disabled || !agent.configured || !agent.depth.installed;
      el('agent-local').disabled = disabled || !agent.depth.installed;
      el('agent-capture').disabled = disabled;
      el('agent-observation').textContent = agent.observation?.summary || '';
      el('agent-sample').textContent = agent.sample_path ? 'Saved: ' + agent.sample_path : '';
      const report = agent.observation?.depth;
      el('agent-depth-info').textContent = agent.depth.installed
        ? 'Depth Anything V2 Small (24.8M)' + (report ? ' | ' + report.device + ' | ' + report.inference_seconds + ' s | ' + report.units : ' | ready')
        : 'Depth runtime missing. Run operator_ui/setup_depth.ps1 and restart with .venv-depth.';
      const preview = el('agent-depth-preview');
      preview.hidden = !agent.depth_available;
      if (agent.depth_available && previewSample !== agent.sample_path) {
        previewSample = agent.sample_path;
        preview.src = '/agent/image?kind=depth&t=' + Date.now();
      }
      if (Date.now() >= pinnedUntil) {
        if (sequence.name === 'camera_agent') {
          if (sequence.active) status(sequence.log?.at(-1)?.msg || 'Processing scene...');
          else if (sequence.result) status(sequence.result.ok ? 'Scene request complete. No robot motion.' : sequence.result.error);
        } else status(agent.configured ? 'Ready to analyze a camera scene.' : 'Local depth and captures are ready. Add an API key for Haiku descriptions.');
      }
    } catch (error) { status('Scene agent unavailable. Reload after restarting Flask.'); }
    finally { setTimeout(poll, 1500); }
  }
  poll();
})();
