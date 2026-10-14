/* Offline only. No robot API calls. Export is a kinematic reference, not a motion job. */
const S4Demo = (() => {
  let recording=false, starting=false, samples=[], scene=null, started=0, path=null;
  const status=s=>el('demo-status').textContent=s;
  const value=id=>{const v=Number(el(id).value);if(!el(id).value||!Number.isFinite(v))throw Error('Enter '+id);return v;};
  function sample(){
    gripper();
    if(!recording||!three?.previewPose)return;
    const e1=Number(el('demo-e1').value);
    if(el('demo-e1').value===''||!Number.isFinite(e1)||e1<0||e1>28){status('Enter simulated E1 between 0 and 28 mm; sample not recorded.');return;}
    const q=three.previewPose, ref=previewReference();
    if(JSON.stringify(ref)!==JSON.stringify(scene.reference)){stop();status('Reference changed; recording stopped. Start a new recording.');return;}
    const row={t:(performance.now()-started)/1000,J1:q.z-ref.zOffset,J2:q.J2,J3:q.J3,
      J4:q.rz-q.J2-q.J3-ref.wristOffset,z:q.z,rz:q.rz,...S4Preview.forward(q,RP),
      e1_mm:e1,phase:el('demo-phase').value};
    const last=samples.at(-1);
    if(last&&Object.keys(row).every(k=>k==='t'||row[k]===last[k]))return;
    row.t=last?Math.max(row.t,last.t+0.001):0;
    samples.push(row);draw();status(`${samples.length} keyframes recorded — colored preview only.`);
  }
  function draw(){
    if(!three?.world)return;
    if(path){three.world.remove(path);path.geometry.dispose();path.material.dispose();}
    path=new THREE.Line(new THREE.BufferGeometry().setFromPoints(samples.map(s=>new THREE.Vector3(s.x,s.y,s.z))),new THREE.LineBasicMaterial({color:0x00e5ff}));
    three.world.add(path);
  }
  async function start(){
    try{
      if(recording||starting)throw Error('Already recording or starting');
      if(samples.length&&!confirm('Replace the current recording? Export it first if needed.'))return;
      if(!three?.previewPose||!RP)throw Error('Initialize the colored preview first');
      starting=true;
      const response=await fetch('/static/models/plate_rack_config.json');
      if(!response.ok)throw Error('Rack configuration unavailable');
      const rack={...await response.json(),...Object.fromEntries(['x','y','z','rz','shelf'].map(k=>[k,value('rack-'+k)]))};
      scene={robot:{...RP},reference:{...previewReference()},rack,
        plate:{x:value('demo-x'),y:value('demo-y'),support_top_mm:value('demo-support'),yaw_deg:value('demo-yaw'),length_mm:127.76,width_mm:85.48,height_mm:14.4,mass_kg:0.12},
        assumptions:'Plate size/mass, support, arm collision shapes, gripper and dynamics are estimates. Rack pose captured at recording start. Not hardware-safe.'};
      samples=[];started=performance.now();recording=true;
      for(const e of document.querySelectorAll('[data-demo-scene], #rack-x, #rack-y, #rack-z, #rack-rz, #rack-shelf'))e.disabled=true;
      sample();
    }catch(e){status(e.message);}finally{starting=false;}
  }
  function stop(){recording=false;for(const e of document.querySelectorAll('[data-demo-scene], #rack-x, #rack-y, #rack-z, #rack-rz, #rack-shelf'))e.disabled=false;status(`Stopped: ${samples.length} keyframes. Export JSON for MuJoCo replay.`);}
  function save(){
    if(recording){status('Stop recording before export.');return;}
    if(samples.length<2){status('Record at least two different keyframes.');return;}
    const data={schema:'bioyond-demo-v1',units:{distance:'mm',angle:'deg',time:'s'},created_at:new Date().toISOString(),scene,samples};
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='s4-demo-'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  function gripper(){
    if(!three?.ghostGroups)return;
    if(!three.demoGripper){
      const g=new THREE.Group();three.ghostGroups.wrist.add(g);
      const material=new THREE.MeshStandardMaterial({color:0xd690ee,metalness:0.25,roughness:0.5});
      const box=(x,y,z,dx,dy,dz)=>{const m=new THREE.Mesh(new THREE.BoxGeometry(dx,dy,dz),material);m.position.set(x,y,z);g.add(m);return m;};
      box(95.8,5.43,22,191.6,14,10);
      box(191.6,5.43,22,18,106,10);
      const jaws=[-1,1].map(s=>box(191.6,5.43+s*46,0,70,6,28));
      three.demoGripper={g,jaws};
    }
    const {g,jaws}=three.demoGripper;
    g.rotation.z=(three.RZ_REF??0)*Math.PI/180;
    const gap=60+Math.max(0,Math.min(28,Number(el('demo-e1').value)||0));
    jaws.forEach((m,i)=>m.position.y=5.43+(i?1:-1)*(gap/2+3));
  }
  function plate(){
    if(!three?.world)return;
    if(!three.demoPlate){
      const group=new THREE.Group();three.world.add(group);
      const body=new THREE.Mesh(new THREE.BoxGeometry(127.76,85.48,14.4),new THREE.MeshStandardMaterial({color:0x33d9d9}));group.add(body);
      const support=new THREE.Mesh(new THREE.BoxGeometry(127.76,85.48,1),new THREE.MeshStandardMaterial({color:0x43576e}));group.add(support);
      three.demoPlate={group,body,support};
    }
    const {group,body,support}=three.demoPlate;
    const x=Number(el('demo-x').value),y=Number(el('demo-y').value),z=Math.max(1,Number(el('demo-support').value));
    group.position.set(x,y,0);group.rotation.z=Number(el('demo-yaw').value)*Math.PI/180;
    body.position.z=z+7.2;support.position.z=z/2;support.scale.z=z;
  }
  for(const input of document.querySelectorAll('[data-demo-scene]'))input.addEventListener('input',plate);
  return {start,stop,save,sample,gripper,plate};
})();
