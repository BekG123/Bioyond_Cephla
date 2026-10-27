/* Developer-only reference review and model transcript. No motion controls. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  let candidate = null, pending = false, revision = '';
  const notice = value => { $('imitation-dev-notice').textContent = value; };
  async function request(path, body) {
    const response = await fetch(path, body === undefined ? {cache:'no-store',headers:{'X-Cephla-View':'developer'}} : {
      method:'POST',headers:{'Content-Type':'application/json','X-Cephla-View':'developer'},body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || result.message || 'Request failed.');
    return result;
  }
  $('imitation-key-save').onclick = async () => {
    try {
      await request('/agent/settings',{api_key:$('imitation-key').value});
      notice('Haiku key saved securely on this computer and restored after reloads. No movement requested.');
    } catch(error) { notice(error.message); }
    finally { $('imitation-key').value = ''; }
  };
  function resetReview() {
    candidate = null; $('imitation-review').checked = false; $('imitation-approve').disabled = true;
  }
  $('imitation-source').oninput = resetReview;
  $('imitation-load').onclick = async () => {
    resetReview();
    try {
      const data = await request('/imitation/reference?source_id=' + encodeURIComponent($('imitation-source').value.trim()));
      candidate = data.reference;
      $('imitation-reference').textContent = JSON.stringify(candidate,null,2);
      notice('Check the measured endpoints and path before saving.');
    } catch(error) { $('imitation-reference').textContent = ''; notice(error.message); }
  };
  $('imitation-review').onchange = () => { $('imitation-approve').disabled = !candidate || !$('imitation-review').checked; };
  $('imitation-approve').onclick = async () => {
    if (!candidate || !$('imitation-review').checked) return;
    try {
      await request('/imitation/reference',{source_id:candidate.source_id,reference_id:candidate.id,reviewed_clear_path:true});
      notice('Reference saved. Use Researcher view → Run for Descend and Grip.'); resetReview();
    } catch(error) { notice(error.message); }
  };
  async function poll() {
    if (pending) return;
    pending = true;
    try {
      const data = await request('/imitation/state?since=' + encodeURIComponent(revision));
      $('imitation-dev-status').textContent = data.model + ' · ' + data.stage + ' · ' + (data.blocker || data.message);
      $('pickup-plan-result').textContent = data.pickup_plan ? JSON.stringify(data.pickup_plan,null,2) : 'No pickup proposal yet.';
      if (!data.unchanged) $('imitation-transcript').textContent = data.events.length ? JSON.stringify(data.events,null,2) : 'No imitation requests yet.';
      revision = String(data.event_revision);
    } catch { $('imitation-dev-status').textContent = 'Imitation status unavailable.'; }
    finally { pending = false; }
  }
  poll(); setInterval(poll,1500);
})();
