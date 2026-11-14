"use strict";
// AnimFactory normalized keyframe authoring. This is an editor-only curve preview;
// authoritative pose, IK and movie frames still come from Python motion_clips.py.
const ce = id => document.getElementById(id);
const channels = [
  "root_x","root_y","left_x","left_y","right_x","right_y",
  "lean","head_turn","sitting","blink"
];
const curveUI = {id:"",channel:"",draft:null,selected:0,drag:false,ranges:null};
function curveStatus(text,error=false){
  ce("curveStatus").textContent=text;
  ce("curveStatus").style.color=error?"#ffb4bb":"#9fd6b6";
}
function curveClone(value){return JSON.parse(JSON.stringify(value));}
function curveClipIds(){return Object.keys(state.doc?.motion_library?.clips||{}).sort();}
function curveTrack(){return curveUI.draft?.tracks?.[curveUI.channel]||null;}
function curveKeys(){return curveTrack()?.keys||[];}
function curveRefreshList(preferred=null){
  const list=ce("curveMotion"),options=curveClipIds();
  const selection=preferred||curveUI.id;
  list.replaceChildren();
  for(const id of options){
    const option=document.createElement("option");option.value=id;option.textContent=id;
    list.append(option);
  }
  curveUI.id=options.includes(selection)?selection:(options[0]||"");
  list.value=curveUI.id;
  if(!curveUI.id){
    curveUI.draft=null;curveStatus("Create a motion clip first.");curvePaint();
    return;
  }
  curveUI.draft=curveClone(state.doc.motion_library.clips[curveUI.id]);
  curveUI.channel=Object.hasOwn(curveUI.draft.tracks,curveUI.channel)?
    curveUI.channel:Object.keys(curveUI.draft.tracks)[0];
  curveUI.selected=0;
  curvePopulate();
}
function curvePopulate(){
  const draft=curveUI.draft;
  if(!draft)return;
  ce("curveDuration").value=draft.duration;
  ce("curveLoop").checked=draft.loop===true;
  const select=ce("curveChannel");select.replaceChildren();
  for(const key of Object.keys(draft.tracks)){
    const option=document.createElement("option");option.value=key;option.textContent=key;
    select.append(option);
  }
  select.value=curveUI.channel;
  ce("curveMode").value=curveTrack().mode||"linear";
  curveUI.selected=Math.min(curveUI.selected,curveKeys().length-1);
  curveInputKey();curvePaint();
}
function curveInputKey(){
  const key=curveKeys()[curveUI.selected];
  if(!key)return;
  ce("curveTime").value=key[0];
  ce("curveValue").value=key[1];
}
function curveRange(){
  const chan=curveUI.channel;
  let lower=-240,upper=240;
  if(chan==="sitting"||chan==="blink"){lower=0;upper=1;}
  else if(chan==="lean"||chan==="head_turn"){lower=-70;upper=70;}
  for(const item of curveKeys()){
    lower=Math.min(lower,item[1]-5);
    upper=Math.max(upper,item[1]+5);
  }
  if(upper-lower<1)upper=lower+1;
  return [lower,upper];
}
function curveSample(points,t,mode){
  if(!points.length)return 0;
  if(t<=points[0][0])return points[0][1];
  if(t>=points[points.length-1][0])return points[points.length-1][1];
  for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i];
    if(t>b[0])continue;
    let u=(t-a[0])/(b[0]-a[0]);
    if(mode==="step")u=0;
    else if(mode==="smooth")u=u*u*(3-2*u);
    return a[1]+(b[1]-a[1])*u;
  }
  return points[points.length-1][1];
}
function curvePaint(){
  const canvas=ce("curveCanvas"),ctx=canvas.getContext("2d");
  const w=canvas.width,h=canvas.height,left=52,right=w-20,top=20,bottom=h-32;
  ctx.fillStyle="#172338";ctx.fillRect(0,0,w,h);
  const tr=curveTrack();
  if(!tr){ctx.fillStyle="#b9c8e2";ctx.fillText("Choose or create a named motion clip",30,40);return;}
  const [min,max]=curveRange();
  curveUI.ranges={left,right,top,bottom,min,max};
  const tx=t=>left+t*(right-left);
  const vy=v=>bottom-(v-min)/(max-min)*(bottom-top);
  ctx.lineWidth=1;ctx.strokeStyle="#344762";ctx.fillStyle="#a5badd";ctx.font="12px sans-serif";
  for(let i=0;i<=10;i++){
    const x=tx(i/10);ctx.beginPath();ctx.moveTo(x,top);ctx.lineTo(x,bottom);ctx.stroke();
    if(i%2===0)ctx.fillText((i/10).toFixed(1),x-9,bottom+17);
  }
  for(let i=0;i<=4;i++){
    const y=top+(bottom-top)*i/4;ctx.beginPath();ctx.moveTo(left,y);ctx.lineTo(right,y);ctx.stroke();
    const v=max-(max-min)*i/4;ctx.fillText(Number(v.toFixed(1)).toString(),4,y+4);
  }
  ctx.strokeStyle="#78b2ff";ctx.lineWidth=2.5;ctx.beginPath();
  for(let i=0;i<=240;i++){
    const x=i/240;
    const y=curveSample(tr.keys,x,tr.mode||"linear");
    if(i===0)ctx.moveTo(tx(x),vy(y));
    else ctx.lineTo(tx(x),vy(y));
  }
  ctx.stroke();
  for(let i=0;i<tr.keys.length;i++){
    const key=tr.keys[i];
    ctx.beginPath();
    ctx.fillStyle=i===curveUI.selected?"#ffad58":"#8ee4bf";
    ctx.strokeStyle="#172638";ctx.lineWidth=3;
    ctx.arc(tx(key[0]),vy(key[1]),7,0,Math.PI*2);ctx.fill();ctx.stroke();
  }
  ctx.fillStyle="#c7d8f4";ctx.fillText(curveUI.channel+" · "+(tr.mode||"linear"),left+3,13);
}
function curvePointer(event){
  const canvas=ce("curveCanvas"),rect=canvas.getBoundingClientRect();
  return [(event.clientX-rect.left)*canvas.width/rect.width,
          (event.clientY-rect.top)*canvas.height/rect.height];
}
function curveStartDrag(event){
  if(!curveTrack()||!curveUI.ranges)return;
  const [x,y]=curvePointer(event),r=curveUI.ranges;
  let closest=-1,best=32;
  curveKeys().forEach(([t,v],i)=>{
    const xx=r.left+t*(r.right-r.left);
    const yy=r.bottom-(v-r.min)/(r.max-r.min)*(r.bottom-r.top);
    const d=Math.hypot(x-xx,y-yy);
    if(d<best){closest=i;best=d;}
  });
  if(closest<0)return;
  curveUI.selected=closest;curveUI.drag=true;
  ce("curveCanvas").setPointerCapture(event.pointerId);
  curveMoveDrag(event);
}
function curveMoveDrag(event){
  if(!curveUI.drag||!curveTrack()||!curveUI.ranges)return;
  const [x,y]=curvePointer(event),r=curveUI.ranges;
  const keys=curveKeys(),index=curveUI.selected;
  const clamp=(v,a,b)=>Math.min(b,Math.max(a,v));
  let t=clamp((x-r.left)/(r.right-r.left),0,1);
  if(index===0)t=0;
  else if(index===keys.length-1)t=1;
  else t=clamp(t,keys[index-1][0]+.001,keys[index+1][0]-.001);
  let value=r.min+(r.bottom-y)/(r.bottom-r.top)*(r.max-r.min);
  if(curveUI.channel==="sitting"||curveUI.channel==="blink")value=clamp(value,0,1);
  keys[index]=[Number(t.toFixed(4)),Number(value.toFixed(3))];
  curveInputKey();curvePaint();curveStatus("Unsaved curve edit. Click Save motion clip.");
}
function curveEndDrag(){curveUI.drag=false;}
function curveApplyKey(){
  const keys=curveKeys(),i=curveUI.selected;
  if(!keys[i])throw Error("Select a keyframe first");
  const time=Number(ce("curveTime").value),value=Number(ce("curveValue").value);
  if(!Number.isFinite(time)||!Number.isFinite(value)||time<0||time>1)throw Error("Keys need finite time 0..1 and value");
  const lower=i===0?0:keys[i-1][0]+.001;
  const upper=i===keys.length-1?1:keys[i+1][0]-.001;
  if(time<lower||time>upper)throw Error("Keyframes must stay strictly ordered");
  keys[i]=[Number(time.toFixed(4)),value];curvePaint();
  curveStatus("Unsaved numeric key edit. Click Save motion clip.");
}
async function curveSave(){
  if(!curveUI.id||!curveUI.draft)throw Error("Choose a motion");
  const duration=Number(ce("curveDuration").value);
  if(!Number.isFinite(duration)||duration<=0||duration>300)throw Error("Duration must be 0–300 seconds");
  curveUI.draft.duration=duration;
  curveUI.draft.loop=ce("curveLoop").checked;
  const tr=curveTrack();
  tr.mode=ce("curveMode").value;
  if(curveUI.draft.loop){
    for(const [channel,track] of Object.entries(curveUI.draft.tracks)){
      const first=track.keys[0],last=track.keys.at(-1);
      if(first[0]!==0||last[0]!==1||Math.abs(first[1]-last[1])>1e-6)
        throw Error("Loop channel "+channel+" needs equal values at time 0 and 1");
    }
  }
  const id=curveUI.id;
  await edit({op:"set",path:"/motion_library/clips/"+id,value:curveUI.draft});
  curveUI.id=id;
  curveStatus("Saved "+id+" to project.json. All actors referencing it now reuse this curve.");
}
async function curveCreate(duplicate=false){
  if(!state.doc)throw Error("Project is not loaded");
  const preferred=duplicate&&curveUI.id?curveUI.id+"_copy":"new_motion";
  const id=prompt("New reusable motion ID:",preferred);
  if(!id)return;
  if(!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(id))throw Error("ID must use letters, digits, underscore or dash, starting with a letter");
  if(Object.hasOwn(state.doc.motion_library.clips,id))throw Error("That motion ID already exists");
  const source=duplicate&&curveUI.draft?curveClone(curveUI.draft):{
    duration:1.2,loop:false,
    tracks:{
      right_x:{mode:"smooth",keys:[[0,70],[.5,110],[1,70]]},
      right_y:{mode:"smooth",keys:[[0,-60],[.5,-130],[1,-60]]}
    }
  };
  await edit({op:"add",path:"/motion_library/clips/"+id,value:source});
  curveUI.id=id;curveRefreshList(id);
  curveStatus("New reusable clip "+id+" created and saved.");
}
function curveAddTrack(){
  if(!curveUI.draft)throw Error("Choose a clip first");
  const available=channels.filter(ch=>!Object.hasOwn(curveUI.draft.tracks,ch));
  if(!available.length)throw Error("All rig-local motion channels already exist");
  const channel=prompt("Add rig-local channel: "+available.join(", "),available[0]);
  if(!channel)return;
  if(!available.includes(channel))throw Error("Select an unused supported channel");
  curveUI.draft.tracks[channel]={mode:"smooth",keys:[[0,0],[1,0]]};
  curveUI.channel=channel;curveUI.selected=0;curvePopulate();
  curveStatus("Unsaved new channel. Click Save motion clip.");
}
function curveRemoveTrack(){
  if(!curveUI.draft||!curveTrack())throw Error("Choose a track");
  if(Object.keys(curveUI.draft.tracks).length===1)throw Error("A motion must have at least one channel");
  delete curveUI.draft.tracks[curveUI.channel];
  curveUI.channel=Object.keys(curveUI.draft.tracks)[0];
  curvePopulate();curveStatus("Unsaved channel removal. Click Save motion clip.");
}
function curveAddKey(){
  const keys=curveKeys(),track=curveTrack();
  if(!track)throw Error("Choose a clip/channel first");
  if(keys.length>=40)throw Error("Maximum 40 keys per channel");
  let split=-1,span=0;
  for(let i=1;i<keys.length;i++){
    const gap=keys[i][0]-keys[i-1][0];
    if(gap>span){split=i;span=gap;}
  }
  if(split<0||span<.002)throw Error("No room between existing key times");
  const t=(keys[split-1][0]+keys[split][0])/2;
  const value=curveSample(keys,t,track.mode);
  keys.splice(split,0,[Number(t.toFixed(4)),Number(value.toFixed(3))]);
  curveUI.selected=split;curveInputKey();curvePaint();
  curveStatus("Unsaved keyframe added. Click Save motion clip.");
}
function curveRemoveKey(){
  const keys=curveKeys();
  if(keys.length<=1)throw Error("Cannot remove the final keyframe");
  keys.splice(curveUI.selected,1);
  curveUI.selected=Math.max(0,Math.min(curveUI.selected,keys.length-1));
  curveInputKey();curvePaint();
  curveStatus("Unsaved keyframe removal. Click Save motion clip.");
}
function curveGuard(action){
  return ()=>Promise.resolve().then(action).catch(e=>curveStatus(e.message,true));
}
function curveWire(){
  ce("curveMotion").addEventListener("change",()=>curveRefreshList(ce("curveMotion").value));
  ce("curveChannel").addEventListener("change",()=>{
    curveUI.channel=ce("curveChannel").value;curveUI.selected=0;curvePopulate();
  });
  ce("curveMode").addEventListener("change",()=>{
    if(!curveTrack())return;curveTrack().mode=ce("curveMode").value;curvePaint();
    curveStatus("Unsaved interpolation change.");
  });
  ce("curveNew").onclick=curveGuard(()=>curveCreate());
  ce("curveDuplicate").onclick=curveGuard(()=>curveCreate(true));
  ce("curveSave").onclick=curveGuard(curveSave);
  ce("curveAddTrack").onclick=curveGuard(curveAddTrack);
  ce("curveRemoveTrack").onclick=curveGuard(curveRemoveTrack);
  ce("curveAddKey").onclick=curveGuard(curveAddKey);
  ce("curveRemoveKey").onclick=curveGuard(curveRemoveKey);
  ce("curveApplyKey").onclick=curveGuard(curveApplyKey);
  const canvas=ce("curveCanvas");
  canvas.addEventListener("pointerdown",curveStartDrag);
  canvas.addEventListener("pointermove",curveMoveDrag);
  canvas.addEventListener("pointerup",curveEndDrag);
  canvas.addEventListener("pointercancel",curveEndDrag);
  window.addEventListener("animfactory:project-updated",()=>curveRefreshList());
  window.addEventListener("animfactory:motion-picked",e=>{
    if(e.detail.kind!=="keyframed")return;
    curveUI.id=e.detail.id;curveRefreshList(e.detail.id);
  });
}
curveWire();
