"""Update only the read-only animation and export its recorded run."""
from pathlib import Path
import json

page = Path('operator_ui/static/hamilton-dry-run.html')
html = page.read_text(encoding='utf-8')
html = html.replace('#pipette{transition:transform 1.1s cubic-bezier(.4,0,.2,1)}', '')
html = html.replace('<script>\nconst NS=', '<script id="recorded-run" type="application/json">null</script>\n<script>\nconst NS=')
html = html[:html.index('let data=')] + '''const recorded=JSON.parse($('#recorded-run').textContent);
let data=recorded||{events:[],completed:0,status:'Ready for dry run'};
let replayEvents=[],replaying=false,playing=false,seconds=0,lastFrame=null;
const home={x:95,y:120};
function position(e){
  if(!e)return home;
  if(e.mode==='Pick-Up Tips')return tips[e.column-1];
  if(e.mode==='Aspirate')return wells['2:0:0'];
  if(e.mode==='Dispense')return wells['3:0:'+(e.column-1)];
  return {x:855,y:382};
}
function draw(events,complete,status,pos){
  const e=events.at(-1);let text=status;
  for(const [key,w] of Object.entries(wells)){
    const done=key.startsWith('3:0:')&&Number(key.split(':')[2])<complete;
    const active=e&&((e.mode==='Aspirate'&&key==='2:0:0')||(e.mode==='Dispense'&&key==='3:0:'+(e.column-1)));
    w.e.setAttribute('class','well'+(done?' done':'')+(active?' active':''));
  }
  tips.forEach((t,i)=>t.e.setAttribute('class','tip'+(i<complete?' used':'')));
  if(e){
    const labels={'Pick-Up Tips':'Pick up fresh tip · well A'+e.column,'Aspirate':'Aspirate air · site 2 A1','Dispense':'Dispense air · site 3 A'+e.column,'Eject Tips':'Discard tip · well A'+e.column};
    text=status==='Completed'?'Completed · six wells':status.startsWith('Stopped')?status:labels[e.mode]||status;
  }
  pos=pos||position(e);
  $('#pipette').setAttribute('transform',`translate(${pos.x} ${pos.y-45})`);
  $('#phase').textContent=text;$('#count').textContent=complete+' / 6 wells';$('#progress').value=complete;
  document.body.dataset.rendered='true';
}
function replayFrame(){
  if(!replayEvents.length)return;
  const ev=replayEvents,first=ev[0].at,span=ev.at(-1).at+3-first;
  const t=first+span*seconds/30,visible=ev.filter(e=>e.at<=t),index=visible.length-1;
  const target=position(ev[index]),previous=position(ev[index-1]);
  const eventTime=(ev[index].at-first)*30/span;
  const nextTime=index+1<ev.length?(ev[index+1].at-first)*30/span:30;
  const fraction=Math.min(1,Math.max(0,(seconds-eventTime)/Math.min(.65,(nextTime-eventTime)*.75)));
  const ease=fraction*fraction*(3-2*fraction);
  const pos={x:previous.x+(target.x-previous.x)*ease,y:previous.y+(target.y-previous.y)*ease};
  const done=seconds>=30?6:visible.filter(e=>e.mode==='Eject Tips').length;
  draw(visible,done,seconds>=30?'Completed':'Replay',pos);
  $('#scrub').value=seconds;$('#clock').textContent=seconds.toFixed(1)+' / 30 s';
}
function showLive(){
  const stale=data.updated&&Date.now()/1000-data.updated>8&&data.status!=='Completed';
  draw(data.events||[],data.completed||0,stale?'Feedback stale — motion state unknown':data.status);
  $('#clock').textContent=stale?'Feedback stale':data.status==='Completed'?'Run report verified':'Listening to Hamilton';
}
function acceptData(){
  $('#replay').disabled=data.status!=='Completed'||!data.events?.length;
  if(!replaying)showLive();
}
async function poll(){
  try{const r=await fetch('/data',{cache:'no-store'});data=await r.json();acceptData();}
  catch(e){if(!replaying)$('#phase').textContent='Feedback unavailable';}
  setTimeout(poll,600);
}
function startReplay(){
  replayEvents=(data.events||[]).slice().sort((a,b)=>a.at-b.at);
  if(!replayEvents.length)return;
  replaying=true;playing=true;seconds=0;lastFrame=null;
  $('#live').classList.remove('selected');$('#replay').classList.add('selected');
  $('#pause').disabled=false;$('#pause').textContent='Pause replay';$('#scrub').disabled=false;
  $('#modeLabel').textContent='30-second replay of recorded events';replayFrame();
}
$('#replay').onclick=startReplay;
$('#live').onclick=()=>{
  replaying=false;playing=false;lastFrame=null;
  $('#live').classList.add('selected');$('#replay').classList.remove('selected');
  $('#pause').disabled=true;$('#scrub').disabled=true;
  $('#modeLabel').textContent=recorded?'Recorded run result':'Live instrument events';showLive();
};
$('#pause').onclick=()=>{
  if(!playing&&seconds>=30){startReplay();return;}
  playing=!playing;lastFrame=null;$('#pause').textContent=playing?'Pause replay':'Resume replay';
};
$('#scrub').oninput=e=>{
  seconds=+e.target.value;playing=false;lastFrame=null;
  $('#pause').textContent=seconds>=30?'Play again':'Resume replay';replayFrame();
};
document.addEventListener('visibilitychange',()=>{lastFrame=null;});
function frame(now){
  if(replaying&&playing&&!document.hidden){
    if(lastFrame!==null)seconds=Math.min(30,seconds+Math.min(.1,Math.max(0,(now-lastFrame)/1000)));
    replayFrame();
    if(seconds>=30){playing=false;$('#pause').textContent='Play again';}
  }
  lastFrame=now;requestAnimationFrame(frame);
}
draw([],0,'Ready for dry run');
if(recorded){$('#live').textContent='Run result';acceptData();startReplay();}else poll();
requestAnimationFrame(frame);
</script></body></html>
'''
page.write_text(html, encoding='utf-8')
snapshot=json.loads(Path('operator_ui/reports/hamilton_api/dry_run_60910d1cfa244d2ab20f38ce4b07636a/animation_events.json').read_text())
export=html.replace('<script id="recorded-run" type="application/json">null</script>', '<script id="recorded-run" type="application/json">'+json.dumps(snapshot).replace('<','\\u003c')+'</script>')
Path('work/hamilton-dry-run-replay.html').write_text(export,encoding='utf-8')
print('Updated live viewer and self-contained recorded replay; no instrument access.')
