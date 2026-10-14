/* Independent depth camera display; no robot commands. */
window.RealSenseUI = (() => {
  const byId = id => document.getElementById(id);
  let starting = false, busy = false, polling = false, fresh = false;
  const visible = () => byId('tab-depth').style.display !== 'none';
  function buttons() {
    for (const name of ['start','stop','demo']) byId('rs-'+name).disabled = busy;
    for (const name of ['snapshot','export']) byId('rs-'+name).disabled = busy || !fresh;
  }
  async function request(path, body) {
    const response = await fetch('/realsense/'+path, body === undefined ? {cache:'no-store'} : {
      method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)
    });
    const result = await response.json();
    if (!response.ok || result.ok === false) throw new Error(result.error || 'Depth service unavailable');
    return result;
  }
  function display(s) {
    fresh = !!s.streaming;
    const label = s.mode === 'demo' ? 'SYNTHETIC SAMPLE · ' : '';
    byId('rs-status').textContent = label + s.state.toUpperCase() +
      (s.device ? ' · '+s.device.name+' · USB '+s.device.usb : '') + (s.error ? '\n'+s.error : '');
    byId('rs-stats').textContent = fresh ?
      `${s.resolution.join(' × ')} · ${s.fps} frames/s · ${s.valid_depth_percent}% valid depth · ${s.points.toLocaleString()} displayed points\nCenter patch: ${s.center_depth_mm === null ? 'no depth' : s.center_depth_mm+' mm'}` :
      'No fresh depth frames. Start D405 after connecting it, or use the labeled sample view.';
    const port = Number(s.viser_port);
    if (port > 0 && port < 65536) {
      const url = new URL(location.href); url.port = String(port); url.pathname = '/'; url.search = ''; url.hash = '';
      if (byId('rs-viewer').src !== url.href) byId('rs-viewer').src = url.href;
      byId('rs-open').href = url.href; byId('rs-open').hidden = false;
    }
    for (const kind of ['color','depth']) {
      const img = byId('rs-'+kind);
      img.hidden = !fresh;
      if (fresh) img.src = '/realsense/image/'+kind+'?t='+Date.now();
      else img.removeAttribute('src');
    }
    buttons();
  }
  async function poll() {
    if (!visible() || polling || busy || starting) return;
    polling = true;
    try { display(await request('status')); }
    catch (e) { fresh = false; buttons(); byId('rs-status').textContent = e.message; }
    finally { polling = false; }
  }
  async function open() {
    if (starting) return;
    starting = true;
    byId('rs-status').textContent = 'Starting depth viewer…';
    try { display(await request('viewer',{})); }
    catch (e) { byId('rs-status').textContent = e.message; }
    finally { starting = false; }
  }
  async function command(action, body) {
    if (busy) return;
    busy = true; buttons(); byId('rs-result').textContent = '';
    try {
      const result = await request(action,body);
      if (action === 'snapshot') byId('rs-result').textContent = 'Saved '+result.source+' capture: '+result.path;
      else display(result);
    } catch (e) { byId('rs-result').textContent = e.message; }
    finally { busy = false; buttons(); await poll(); }
  }
  setInterval(poll,1000);
  return {open,command};
})();
