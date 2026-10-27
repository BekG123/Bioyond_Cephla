/* Developer-only preference capture. All correction targets are controller measurements. */
(() => {
  'use strict';
  const host = document.getElementById('coactive-pickup');
  if (!host) return;
  host.innerHTML = `<h2>Coactive learning — Descend / Grip</h2>
    <p>Developers demonstrate corrections by hand. Review a measured base reference above first. Run one action, demonstrate a better endpoint with the hand-guiding controls, then hold still and capture it here.</p>
    <p>Accepted corrections update the next action's target in this exact taught setup. Haiku receives the preference history; model weights are not trained. No automatic test or motion follows capture or acceptance.</p>
    <p id="coactive-status" role="status"></p>
    <label>Action <select id="coactive-stage"><option>Descend</option><option>Grip</option></select></label>
    <label>Why is this better? <input id="coactive-note" maxlength="1000" placeholder="e.g. previous descent was too low"></label>
    <label><input id="coactive-demonstrated" type="checkbox"> I demonstrated this correction by hand and am holding the arm and jaws still. Plate and frames are unchanged.</label>
    <button id="coactive-capture" disabled>Capture corrected endpoint</button>
    <p>Descend: keep X/Y, wrist angle and open-jaw position unchanged; correct height only. Grip: keep the arm at the descent endpoint; correct jaw closure only.</p>
    <label>Correction to review <select id="coactive-proposal"><option value="">No corrections</option></select></label>
    <pre id="coactive-comparison" style="white-space:pre-wrap;max-height:260px;overflow:auto"></pre>
    <label><input id="coactive-reviewed" type="checkbox"> This measured correction is preferable. I verified the vertical path and jaw clearance; no collision segment is approved.</label>
    <div class="row"><button id="coactive-accept" disabled>Accept improvement</button><button id="coactive-reject" disabled>Keep previous reference</button></div>
    <p id="coactive-notice" role="status"></p>
    <details><summary>Preference history and measured outcomes</summary><pre id="coactive-history" style="white-space:pre-wrap;max-height:300px;overflow:auto"></pre></details>`;
  const $ = id => document.getElementById(id);
  let state = null, pending = false, polling = false, currentId = null;
  async function request(suffix = '',body) {
    const response = await fetch('/developer/api/coactive'+suffix, body === undefined ? {cache:'no-store'} : {
      method:'POST',headers:{'Content-Type':'application/json','X-Cephla-View':'developer'},body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.message || 'Learning request failed.');
    return result;
  }
  function render() {
    $('coactive-status').textContent = state?.blocker || (state?.current ? 'Reference ready. Capture reads measurements only.' : 'Learning status unavailable.');
    const selected = state?.proposals?.find(p => p.id === $('coactive-proposal').value);
    $('coactive-comparison').textContent = selected ? JSON.stringify({action:selected.action,change:selected.change,note:selected.note,status:selected.status,measured_samples:selected.reference.coactive.measured_samples},null,2) : '';
    $('coactive-capture').disabled = pending || !state?.current || !$('coactive-demonstrated').checked;
    $('coactive-accept').disabled = pending || selected?.status !== 'pending' || !$('coactive-reviewed').checked;
    $('coactive-reject').disabled = pending || selected?.status !== 'pending';
  }
  async function poll() {
    if (polling || pending) return;
    polling = true;
    try {
      state = await request();
      if (currentId !== state.current?.id) { $('coactive-reviewed').checked = false; $('coactive-demonstrated').checked = false; }
      currentId = state.current?.id;
      const old = $('coactive-proposal').value;
      const options = (state.proposals || []).slice().reverse().map(p => new Option(p.action+' · '+p.status+' · '+p.at,p.id));
      $('coactive-proposal').replaceChildren(...(options.length ? options : [new Option('No corrections','')]));
      if (options.some(o => o.value === old)) $('coactive-proposal').value = old;
      $('coactive-history').textContent = JSON.stringify({preferences:state.preferences,outcomes:state.outcomes},null,2);
    } catch(error) { state = null; $('coactive-notice').textContent = error.message; }
    finally { polling = false; render(); }
  }
  async function post(action,body) {
    pending = true; render();
    try { $('coactive-notice').textContent = (await request('/'+action,body)).message; }
    catch(error) { $('coactive-notice').textContent = error.message; }
    finally { pending = false; $('coactive-reviewed').checked = false; $('coactive-demonstrated').checked = false; await poll(); }
  }
  $('coactive-demonstrated').onchange = render;
  $('coactive-reviewed').onchange = render;
  $('coactive-proposal').onchange = () => { $('coactive-reviewed').checked = false; render(); };
  $('coactive-capture').onclick = () => post('capture',{action:$('coactive-stage').value,reference_id:currentId,
    manually_demonstrated:$('coactive-demonstrated').checked,note:$('coactive-note').value});
  $('coactive-accept').onclick = () => post('decide',{proposal_id:$('coactive-proposal').value,decision:'accept',reviewed_clear_path:$('coactive-reviewed').checked});
  $('coactive-reject').onclick = () => post('decide',{proposal_id:$('coactive-proposal').value,decision:'reject'});
  poll(); setInterval(poll,2000);
})();
