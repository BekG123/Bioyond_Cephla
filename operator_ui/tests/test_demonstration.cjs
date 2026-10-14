// Pure offline recorder test using real Three.js, a small DOM stub, and no server.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const base=path.resolve(__dirname,'../static');
async function main(){
  const fields={}, get=id=>fields[id]??= {value:'',textContent:'',disabled:false,addEventListener(){}};
  for(const [k,v] of Object.entries({'demo-e1':28,'demo-phase':'approach','demo-x':350,'demo-y':-180,'demo-yaw':0,'demo-support':20,'rack-x':350,'rack-y':180,'rack-z':0,'rack-rz':0,'rack-shelf':2}))get(k).value=String(v);
  let blob,now=1000,clicked=0;
  const ctx=vm.createContext({console,performance:{now:()=>now},el:get,confirm:()=>true,Blob,
    URL:{createObjectURL:b=>{blob=b;return 'blob:test';},revokeObjectURL(){}},setTimeout:f=>f(),
    document:{querySelectorAll:()=>[],createElement:()=>({click(){clicked++;}})},
    fetch:async url=>{assert.equal(url,'/static/models/plate_rack_config.json');return {ok:true,json:async()=>JSON.parse(fs.readFileSync(path.join(base,'models/plate_rack_config.json')))};}});
  vm.runInContext(fs.readFileSync(path.join(base,'vendor/three.min.js'),'utf8'),ctx);
  ctx.RP={...JSON.parse(fs.readFileSync(path.join(base,'../robot_params.json'))),...JSON.parse(fs.readFileSync(path.join(base,'preview_config.json')))};
  vm.runInContext(fs.readFileSync(path.join(base,'preview_limits.js'),'utf8'),ctx);
  vm.runInContext('var three={world:new THREE.Group(),ghostGroups:{wrist:new THREE.Group()},previewPose:{J2:-45,J3:90,z:150,rz:45}}; var ref={zOffset:0,wristOffset:0};function previewReference(){return ref;}',ctx);
  vm.runInContext(fs.readFileSync(path.join(base,'demonstration.js'),'utf8')+';globalThis.demo=S4Demo;',ctx);
  ctx.demo.gripper();ctx.demo.plate();
  assert.equal(ctx.three.demoGripper.jaws[1].position.y-ctx.three.demoGripper.jaws[0].position.y-6,88);
  await ctx.demo.start();ctx.demo.sample();
  assert.match(get('demo-status').textContent,/1 keyframes/);
  now+=500;ctx.three.previewPose.z=160;ctx.demo.sample();
  get('demo-e1').value='23';get('demo-phase').value='grasp';ctx.demo.sample();
  assert.equal(ctx.three.demoGripper.jaws[1].position.y-ctx.three.demoGripper.jaws[0].position.y-6,83);
  get('demo-e1').value='';assert.doesNotThrow(()=>ctx.demo.sample());
  get('demo-e1').value='23';ctx.demo.save();assert.equal(clicked,0);
  ctx.demo.stop();ctx.demo.save();assert.equal(clicked,1);
  const out=JSON.parse(await blob.text());
  assert.equal(out.schema,'bioyond-demo-v1');assert.equal(out.samples.length,3);
  assert.equal(out.samples[0].t,0);assert.ok(out.samples[2].t>out.samples[1].t);
  assert.equal(out.samples[1].J1,160);assert.equal(out.samples[2].e1_mm,23);
  assert.equal(out.scene.rack.shelf,2);assert.equal(out.scene.robot.claw_arm_x_mm,191.6);
  await ctx.demo.start();ctx.ref.zOffset=2;ctx.demo.sample();assert.match(get('demo-status').textContent,/Reference changed/);
  console.log('Recorder export, deduplication, units, phase/gripper changes, geometry, invalid input, and reference-change checks passed.');
  return out;
}
module.exports=main();
