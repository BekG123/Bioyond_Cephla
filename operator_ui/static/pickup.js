let pickupView=null,pickupImageToken=null;
async function startPickupVerification(){
  const read=id=>el(id).value===''?NaN:Number(el(id).value);
  const marker_id=read('pickup-marker'),plate_center_dz_mm=read('pickup-dz'),lift_mm=read('pickup-lift');
  if(![marker_id,plate_center_dz_mm,lift_mm].every(Number.isFinite)||!el('pickup-calibrated').checked){el('pickup-status').textContent='Enter plate ID and calibrated Z offset; confirm calibration first.';return;}
  await api('/seq/verify_pickup',{marker_id,plate_center_dz_mm,lift_mm,plate_calibration_confirmed:true,operator_confirmed:true,cell_clear:true},
    `REAL ROBOT MOTION: lift vertically ${lift_mm} mm at speed 5.\n\nAre you at the E-stop, with the plate secured and the lift volume clear?\nNo transfer or automatic release will follow.`);
  await pollPickup();
}
async function pollPickup(){
  try{
    const r=await fetch('/pickup/state',{cache:'no-store'});if(!r.ok)throw Error('Pickup endpoint unavailable; backend update/restart required');
    pickupView=await r.json();el('pickup-status').textContent=pickupView.phase+(pickupView.error?': '+pickupView.error:'');
    el('pickup-export').disabled=!pickupView.verified;
    el('pickup-review').hidden=pickupView.phase!=='awaiting_visual';
    if(pickupView.phase==='awaiting_visual'&&pickupImageToken!==pickupView.token){pickupImageToken=pickupView.token;for(const k of ['before','after'])el('pickup-'+k).src='/pickup/image/'+k+'?token='+encodeURIComponent(pickupImageToken);}
  }catch(e){pickupView=null;el('pickup-export').disabled=true;el('pickup-review').hidden=true;el('pickup-status').textContent=e.message;}
}
async function confirmPickupVisual(confirmed){
  if(pickupView?.phase!=='awaiting_visual')return;
  await api('/pickup/confirm',{token:pickupView.token,confirmed});await pollPickup();
}
async function exportPickupSnapshot(){
  await pollPickup();if(!pickupView?.verified)return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(pickupView.snapshot,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download='post-grasp-'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
setInterval(pollPickup,1500);pollPickup();
