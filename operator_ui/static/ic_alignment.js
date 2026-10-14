// IC capture and image-space preview only. No motion endpoint is called here.
(() => {
  const get = id => document.getElementById(id);
  let referenceKey = '', previewKey = '', busy = false, localError = '';
  async function post(path, body) {
    const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok || result.ok === false) throw new Error(result.error || 'IC request failed');
    return result;
  }
  async function action(fn) {
    if (busy) return;
    busy = true;
    localError = '';
    try { await fn(); await refresh(); }
    catch (error) { localError = error.message; get('ic-status').textContent = error.message; }
    finally { busy = false; }
  }
  get('ic-capture').onclick = () => action(async () => {
    let roi = null;
    if (get('ic-roi-mode').value === 'manual') {
      roi = get('ic-roi').value.split(',').map(v => Number(v.trim()));
      if (roi.length !== 4 || !roi.every(Number.isInteger)) throw new Error('Enter x, y, width, height in native image pixels.');
    }
    await post('/ic/reference/capture', {label:get('ic-label').value, count:Number(get('ic-count').value), roi,
      aligned_confirmed:get('ic-aligned').checked, plate_only_roi:get('ic-plate-only').checked});
    get('ic-status').textContent = 'Capturing stationary reference batch; progress appears in the sequence log.';
    get('ic-aligned').checked = false;
  });
  get('ic-preview').onclick = () => action(async () => {
    const id = get('ic-reference').value;
    if (!id) throw new Error('Capture a reference first.');
    await post('/ic/preview', {id});
  });
  get('ic-reference').onchange = () => action(async () => {
    const id=get('ic-reference').value;
    if(id) await post('/ic/reference/select',{id});
  });
  async function refresh() {
    const response = await fetch('/ic/state', {cache:'no-store'});
    if (!response.ok) throw new Error('IC backend unavailable; restart the updated console.');
    const state = await response.json();
    const key = state.references.map(r=>r.id).join(',')+'|'+state.active_id;
    if (key !== referenceKey) {
      const select=get('ic-reference');
      select.replaceChildren();
      for(const ref of state.references) {
        const option=document.createElement('option');
        option.value=ref.id; option.textContent=ref.label+' — '+new Date(ref.created_utc).toLocaleString();
        select.append(option);
      }
      if(state.active_id) select.value=state.active_id;
      if(!state.references.length) { const option=document.createElement('option'); option.value=''; option.textContent='No references yet'; select.append(option); }
      const img=get('ic-reference-image');
      img.hidden=!state.active_id;
      if(state.active_id) img.src='/ic/image?kind=reference&id='+encodeURIComponent(state.active_id);
      referenceKey=key;
    }
    get('ic-capture').disabled=state.active;
    get('ic-preview').disabled=state.active || !state.active_id;
    get('ic-reference').disabled=state.active;
    get('ic-status').textContent=localError || state.error || (state.active ? state.phase+' — see the sequence log; no robot motion.' :
      state.active_id ? 'Reference ready. Preview compares images only; the existing Align button remains separate.' : 'No reference captured. Prepare the arm manually when ready.');
    const r=state.result;
    if(r && r.correlation !== undefined) {
      get('ic-result').textContent=(r.matched?'IMAGE MATCH':'MATCH REJECTED')+(r.image_aligned?' — within image tolerances':'')+'\n'+
        `Shift at region center: X ${r.shift_x_px.toFixed(2)} px, Y ${r.shift_y_px.toFixed(2)} px\n`+
        `Image rotation: ${r.rotation_deg.toFixed(3)}° clockwise; scale: ${r.scale.toFixed(5)}\n`+
        `Correlation: ${r.correlation.toFixed(4)}; normalized image RMSE: ${r.normalized_rmse.toFixed(4)}\n`+
        `IC computation: ${(r.seconds*1000).toFixed(1)} ms; no robot command generated.`;
      if(r.captured_utc!==previewKey) {get('ic-live-image').src='/ic/image?kind=preview&t='+encodeURIComponent(r.captured_utc);get('ic-live-image').hidden=false;previewKey=r.captured_utc;}
    } else { get('ic-result').textContent=''; get('ic-live-image').hidden=true; }
  }
  setInterval(()=>refresh().catch(()=>{}),1500);
  refresh().catch(error=>{get('ic-status').textContent=error.message;});
})();
