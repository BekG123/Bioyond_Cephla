/* One explicit traversal per click; shared Researcher/Developer route control. */
(() => {
  'use strict';
  const host = document.getElementById('latest-hamilton');
  if (!host) return;
  const view = host.dataset.view || 'researcher';
  const developer = view === 'developer';
  host.innerHTML = `<h2>Home-area ↔ Hamilton</h2>
    ${developer ? `<p>Latest tested route · speed 137 · about 12 seconds of travel each way. Controller preparation may add time.</p>
    <p>Home-area is the demonstrated endpoint near Home, not the saved Home position. Empty-gripper replay only.</p>
    <p>Return Home translation speed is 137. The Home-area ↔ saved Home connector uses three queued waypoints: lift to Z300 mm, translate while adjusting the wrist, then descend. Other Home starts queue their lift and travel/descent separately around any wrist-only rotation, which retains its existing speed limit. These Home profiles are offline-tested; verify physical clearance before running. Auto preparation may close the empty jaws.</p>` : ''}
    <p id="latest-route-status" role="status">Checking route…</p>
    <label class="check-label"><input id="latest-route-ready" type="checkbox"> Gripper empty, route clear, arm released, and E-stop supervised.${developer ? ' Preparing motion may close the empty jaws.' : ''}</label>
    <div class="button-row"><button id="latest-route-start" class="primary" disabled>Run taught route</button>
    <button id="latest-route-stop" class="stop" disabled>Stop route</button></div>
    <progress id="latest-route-progress" max="100" value="0" aria-label="Route progress"></progress>
    <p class="help">${developer ? 'Each press runs one direction. Stop requests a controller program stop; no automatic resume.' : 'Stop ends the run. It will not resume automatically.'} Use the E-stop in an emergency.</p>
    <p id="latest-route-notice" role="status"></p>`;
  const $ = id => document.getElementById(id);
  let state = null, pending = false, polling = false;
  async function request(path, body) {
    const response = await fetch('/researcher/api/' + path, body === undefined ? {cache:'no-store',headers:{'X-Cephla-View':view}} : {
      method:'POST', headers:{'Content-Type':'application/json','X-Cephla-View':view}, body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.message || 'Route request failed.');
    return result;
  }
  function render() {
    $('latest-route-status').textContent = state?.active ? state.message : state?.blocker || state?.message || 'Route unavailable. Check the connection.';
    $('latest-route-start').textContent = state?.direction === 'to_hamilton' ? 'Go to Hamilton' : state?.direction === 'toward_home' ? 'Return to Home-area' : 'Run taught route';
    $('latest-route-start').disabled = pending || !state?.can_start || !$('latest-route-ready').checked;
    $('latest-route-stop').disabled = !state?.active;
    $('latest-route-progress').value = state?.progress || 0;
  }
  async function poll() {
    if (polling) return;
    polling = true;
    try { state = (await request('status')).latest_hamilton; }
    catch { state = null; }
    finally { polling = false; render(); }
  }
  $('latest-route-ready').onchange = render;
  $('latest-route-start').onclick = async () => {
    const body = {ready:$('latest-route-ready').checked,path_id:state?.path_id,direction:state?.direction};
    pending = true; $('latest-route-ready').checked = false; render();
    try { $('latest-route-notice').textContent = (await request('latest-hamilton/start',body)).message; }
    catch(error) { $('latest-route-notice').textContent = error.message; }
    finally { pending = false; await poll(); }
  };
  $('latest-route-stop').onclick = async () => {
    try { $('latest-route-notice').textContent = (await request('latest-hamilton/stop',{})).message; }
    catch(error) { $('latest-route-notice').textContent = error.message; }
    await poll();
  };
  poll(); setInterval(poll,1500);
})();
