/* Scene editing and route preview never command robot motion. */
const TRANSFER_FIELDS = ['id','offset','travel','x','y','z','rz'];
let transferPlan = null, transferPlanKey = '';
function transferValues(){
  const v={};
  for(const k of TRANSFER_FIELDS){
    const s=el('auto-'+k).value.trim();
    if(s==='' || !Number.isFinite(Number(s))) throw new Error('Fill every transfer field with a finite number.');
    v[k]=Number(s);
  }
  return {marker_id:v.id,grip_z_offset_mm:v.offset,travel_z:v.travel,destination:{x:v.x,y:v.y,z:v.z,rz:v.rz}};
}
function invalidateTransfer(){
  el('auto-clear').checked=false; transferPlan=null; drawTransferPlan();
  el('auto-status').textContent='Settings changed. Detect & preview again, then verify the route.';
}
function transferUseCurrent(){
  if(!LASTPOSE){el('auto-status').textContent='No live robot pose available.';return;}
  for(const [k,a] of [['x','X'],['y','Y'],['z','Z'],['rz','Rz']]) el('auto-'+k).value=LASTPOSE[a];
  invalidateTransfer();
}
function saveTransferFields(){
  try{
    transferValues();
    localStorage.setItem('bioyond-transfer-v1',JSON.stringify(Object.fromEntries(TRANSFER_FIELDS.map(k=>[k,el('auto-'+k).value]))));
    el('auto-status').textContent='Fields saved in this browser; run confirmation is never saved.';
  }catch(e){el('auto-status').textContent=e.message;}
}
async function startTransfer(preview){
  try{
    const body=transferValues();
    if(!preview && !el('auto-clear').checked) throw new Error('Verify the commissioning checklist before starting.');
    const d=body.destination;
    const msg=preview?null:`MOVE REAL ROBOT: marker ${body.marker_id} plate to TCP X ${d.x}, Y ${d.y}, Z ${d.z}, Rz ${d.rz}, via Z ${body.travel_z}?\nHuman at E-stop, Squid stationary, gripper empty, full swept route clear?`;
    body.confirm=!preview; body.cell_clear=el('auto-clear').checked;
    const response=await api(preview?'/seq/transfer_preview':'/seq/transfer',body,msg);
    if(response){
      el('auto-status').textContent=response.ok?'Sequence started; obtaining fresh observations.':response.error;
      el('auto-clear').checked=false;transferPlan=null;drawTransferPlan();
    }
  }catch(e){el('auto-status').textContent=e.message;}
}
function renderTransfer(s){
  if(!s.name?.startsWith('aruco_transfer')) return;
  el('auto-log').textContent=(s.log||[]).map(e=>`[${e.t.toFixed(1)}] ${e.msg}`).join('\n');
  el('auto-status').textContent=`${s.name}: ${s.state}`+(s.result?.error?' — '+s.result.error:'');
  const key=JSON.stringify(s.result);
  if(key!==transferPlanKey){transferPlanKey=key;transferPlan=s.result?.ok?s.result:null;drawTransferPlan();}
}
function drawTransferPlan(){
  if(!three)return;
  if(three.transferLine){
    three.world.remove(three.transferLine);three.transferLine.geometry.dispose();three.transferLine.material.dispose();three.transferLine=null;
  }
  if(!transferPlan?.plan)return;
  const poses=transferPlan.plan.map(e=>e[1]);if(transferPlan.start)poses.unshift(transferPlan.start);
  const geometry=new THREE.BufferGeometry().setFromPoints(poses.map(p=>new THREE.Vector3(p.X,p.Y,p.Z)));
  const line=new THREE.Line(geometry,new THREE.LineBasicMaterial({color:0xbebebe,depthTest:false}));
  line.renderOrder=10;three.world.add(line);three.transferLine=line;
}
function loadSquidModel(){
  const group=new THREE.Group();three.world.add(group);three.squid=group;
  el('squid-status').textContent='Loading Squid+ C-mount / 4-position turret CAD…';
  new THREE.OBJLoader().load('/static/models/squid_plus_cmount_4turret.obj',object=>{
    object.traverse(c=>{if(c.isMesh){c.geometry.computeVertexNormals();c.material=new THREE.MeshStandardMaterial({color:0x929292,metalness:0.3,roughness:0.6,side:THREE.DoubleSide});}});
    three.squidObject=object;group.add(object);updateSquid();drawTransferPlan();
  },undefined,error=>{el('squid-status').textContent='Squid CAD failed to load; robot view remains usable. Check model asset/server.';console.error('Squid load',error);});
}
function updateSquid(){
  if(!three?.squid)return;
  three.squid.visible=el('squid-visible').checked;
  const raw=['x','y','z','rz'].map(k=>el('squid-'+k).value.trim());
  if(raw.some(v=>v===''||!Number.isFinite(Number(v))))return;
  const [x,y,z,rz]=raw.map(Number);
  three.squid.position.set(x,y,z);three.squid.rotation.z=THREE.MathUtils.degToRad(rz);
  const obj=three.squidObject;if(!obj)return;
  obj.position.set(0,0,0);obj.rotation.set(0,0,0);
  if(el('squid-up').value==='Y')obj.rotation.x=Math.PI/2;
  if(el('squid-up').value==='X')obj.rotation.y=-Math.PI/2;
  obj.updateMatrix();
  const box=new THREE.Box3();
  obj.traverse(c=>{if(c.isMesh){c.geometry.computeBoundingBox();box.union(c.geometry.boundingBox.clone().applyMatrix4(obj.matrix));}});
  const size=box.getSize(new THREE.Vector3());
  obj.position.set(-(box.min.x+box.max.x)/2,-(box.min.y+box.max.y)/2,-box.min.z);
  el('squid-status').textContent=`CAD loaded: ${size.x.toFixed(0)} × ${size.y.toFixed(0)} × ${size.z.toFixed(0)} mm. Placement is visual, not robot calibration.`;
}
function saveSquidPlacement(){
  try{
    localStorage.setItem('bioyond-squid-plus-v1',JSON.stringify(Object.fromEntries(['x','y','z','rz','up'].map(k=>[k,el('squid-'+k).value]))));
    el('squid-status').textContent+=' Saved in this browser.';
  }catch(e){el('squid-status').textContent='Could not save placement: '+e.message;}
}
function focusSquid(){
  if(!three?.squidObject)return;
  three.squid.updateWorldMatrix(true,true);
  const box=new THREE.Box3().setFromObject(three.squid),center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()).length();
  three.controls.target.copy(center);three.camera.position.copy(center).add(new THREE.Vector3(size,size*0.65,size));three.controls.update();
}
(async function(){
  for(const k of TRANSFER_FIELDS)el('auto-'+k).addEventListener('input',invalidateTransfer);
  try{
    const saved=JSON.parse(localStorage.getItem('bioyond-transfer-v1')||'{}');
    for(const k of TRANSFER_FIELDS)if(saved[k]!==undefined)el('auto-'+k).value=saved[k];
    const squid=JSON.parse(localStorage.getItem('bioyond-squid-plus-v1')||'{}');
    for(const k of ['x','y','z','rz','up'])if(squid[k]!==undefined)el('squid-'+k).value=squid[k];
  }catch(e){el('auto-status').textContent='Saved settings unavailable; enter fields manually.';}
  try{
    const r=await fetch('/transfer/config');if(!r.ok)throw new Error('backend update needs Flask restart');
    const c=await r.json();
    el('auto-calibration').textContent=`Calibrated IDs: ${Object.keys(c.markers).join(', ')||'none'}; marker size ${c.marker_size_mm} mm. Camera/claw stamps: ${c.model_stamps.join(' / ')}. Recalibrate if marker or plate changed.`;
    const entry=c.markers[el('auto-id').value];
    if(el('auto-offset').value===''&&entry?.grip_z_offset_mm!==undefined)el('auto-offset').value=entry.grip_z_offset_mm;
  }catch(e){el('auto-calibration').textContent='Transfer configuration unavailable: '+e.message;}
})();
