/* Pure preview kinematics; no network calls or hardware commands. */
const S4Preview = (() => {
  const rad = x => x * Math.PI / 180;
  const deg = x => x * 180 / Math.PI;
  const near = (x, ref) => ref + ((x-ref+180)%360+360)%360-180;
  function forward(q, p) {
    const a = rad(q.J2+p.j2_offset_deg), b = rad(q.J2+q.J3+p.j3_offset_deg);
    return {x:p.base_x_mm+p.link1_mm*Math.cos(a)+p.link2_mm*Math.cos(b),
      y:p.base_y_mm+p.link1_mm*Math.sin(a)+p.link2_mm*Math.sin(b)};
  }
  function error(q, p, ref) {
    if(!['j1_min_mm','j1_max_mm','j3_hard_abs_deg','j2_min_deg','j2_margin_deg','j4_pref_abs_deg','j4_hard_abs_deg','base_x_mm','base_y_mm','link1_mm','link2_mm','j2_offset_deg','j3_offset_deg','extension_margin_mm'].every(k=>Number.isFinite(p[k]))) return 'Missing joint-limit configuration';
    if (![q.J2,q.J3,q.z,q.rz,ref.zOffset,ref.wristOffset].every(Number.isFinite)) return 'Incomplete pose';
    const j1=q.z-ref.zOffset, j4=q.rz-q.J2-q.J3-ref.wristOffset;
    const j2max=Math.abs(p.j2_min_deg)-p.j2_margin_deg;
    const j4max=Math.min(p.j4_pref_abs_deg,p.j4_hard_abs_deg-5);
    if(j1 < p.j1_min_mm-1e-8 || j1 > p.j1_max_mm+1e-8) return 'J1 vertical travel limit';
    if(Math.abs(q.J2)>j2max+1e-8) return 'J2 shoulder limit';
    if(Math.abs(q.J3)>p.j3_hard_abs_deg+1e-8) return 'J3 elbow limit';
    if(Math.abs(j4)>j4max+1e-8) return 'J4 wrist limit';
    const xy=forward(q,p), r=Math.hypot(xy.x-p.base_x_mm,xy.y-p.base_y_mm);
    if(r<20 || r>p.link1_mm+p.link2_mm-p.extension_margin_mm-2) return 'Folded/extended reach limit';
    return '';
  }
  function solve(x,y,z,rz,p,ref,previous) {
    if(![x,y,z,rz].every(Number.isFinite)) return null;
    const dx=x-p.base_x_mm,dy=y-p.base_y_mm,a=p.link1_mm,b=p.link2_mm;
    const c=(dx*dx+dy*dy-a*a-b*b)/(2*a*b);
    if(Math.abs(c)>1) return null;
    const candidates=[1,-1].map(sign=>{
      const beta=sign*Math.acos(c);
      const J2=near(deg(Math.atan2(dy,dx)-Math.atan2(b*Math.sin(beta),a+b*Math.cos(beta)))-p.j2_offset_deg,previous.J2);
      const J3=near(deg(beta)-p.j3_offset_deg+p.j2_offset_deg,previous.J3);
      return {J2,J3,z,rz};
    });
    // Keep the continuous branch, even if the other branch would be valid.
    candidates.sort((a,b)=>Math.hypot(a.J2-previous.J2,a.J3-previous.J3)-Math.hypot(b.J2-previous.J2,b.J3-previous.J3));
    return candidates[0];
  }
  function transition(from,to,p,ref) {
    const endError=error(to,p,ref);
    const n=Math.ceil(Math.max(1,Math.abs(to.J2-from.J2),Math.abs(to.J3-from.J3),Math.abs(to.rz-from.rz),Math.abs(to.z-from.z)/2));
    if(n>2000) return 'Requested movement is too large';
    if(endError) return endError;
    // Check the intervening joint sweep as well as its endpoint.
    for(let i=1;i<=n;i++){
      const q={}; for(const k of ['J2','J3','z','rz']) q[k]=from[k]+(to[k]-from[k])*i/n;
      const why=error(q,p,ref); if(why) return why;
    }
    return '';
  }
  return {near,forward,error,solve,transition};
})();
