/* Visual shelf selection only; no robot commands. */
function loadRackModel(){
  const group=new THREE.Group();three.world.add(group);three.rack=group;
  try{const saved=JSON.parse(localStorage.getItem('bioyond-rack-v1')||'{}');
    for(const k of ['x','y','z','rz','shelf']) if(saved[k]!==undefined) el('rack-'+k).value=saved[k];
  }catch(e){}
  Promise.all([fetch('/static/models/plate_rack.json').then(r=>{if(!r.ok)throw new Error('Rack metadata unavailable');return r.json();}),
    new Promise((resolve,reject)=>new THREE.OBJLoader().load('/static/models/plate_rack.obj',resolve,undefined,reject))])
    .then(([meta,object])=>{
      three.rackMeta=meta;three.rackObject=object;
      object.traverse(c=>{if(c.isMesh){c.geometry.computeVertexNormals();c.material=new THREE.MeshStandardMaterial({color:0xaeb9c5,metalness:0.4,roughness:0.55});}});
      group.add(object);updateRack();
    }).catch(e=>{el('rack-status').textContent='Rack load failed: '+e.message;});
}
function updateRack(){
  if(!three?.rack)return;
  const v=['x','y','z','rz'].map(k=>Number(el('rack-'+k).value));
  if(!v.every(Number.isFinite))return;
  three.rack.visible=el('rack-visible').checked;
  three.rack.position.set(...v.slice(0,3));three.rack.rotation.z=v[3]*Math.PI/180;
  if(!three.rackObject)return;
  const id=Number(el('rack-shelf').value);
  three.rackObject.traverse(c=>{if(c.isMesh)c.material.color.setHex(c.name==='shelf_'+id?0xffb74d:0xaeb9c5);});
  const s=three.rackMeta.shelves.find(s=>s.id===id);
  if(s)el('rack-status').textContent=`Shelf ${id} selected · surface ${s.surface_z_mm} mm above rack base (${(s.surface_z_mm+v[2]).toFixed(1)} mm scene Z). Orange shelf is the target; selection does not move the robot.`;
}
function saveRackPlacement(){
  localStorage.setItem('bioyond-rack-v1',JSON.stringify(Object.fromEntries(['x','y','z','rz','shelf'].map(k=>[k,el('rack-'+k).value]))));
  updateRack();el('rack-status').textContent+=' Placement saved.';
}
function focusRack(){
  if(!three?.rackObject)return;
  const b=new THREE.Box3().setFromObject(three.rack),c=b.getCenter(new THREE.Vector3()),s=b.getSize(new THREE.Vector3()).length();
  three.controls.target.copy(c);three.camera.position.copy(c).add(new THREE.Vector3(s,s*.7,s));three.controls.update();
}
