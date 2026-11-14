"use strict";
const el = id => document.getElementById(id);
const state = {doc:null, rev:null, scene:0, actor:-1, clip:-1, motion:"", frame:0, mode:"blocking", timer:null};
function scene(){return state.doc?.scenes[state.scene]||null;}
function actor(){return scene()?.actors[state.actor]||null;}
function notice(s,error=false){el("diagnostics").textContent=s;el("diagnostics").style.color=error?"#ffb3c0":"#a0d0af";el("saveState").textContent=error?"Check diagnostics":"Saved to project.json";}
async function get(path,opts){const res=await fetch(path,opts);const obj=await res.json();if(!res.ok)throw Error(obj.error||"Request failed");return obj;}
function button(text,active,handler){const b=document.createElement("button");b.textContent=text;b.type="button";b.className=active?"selected":"";b.onclick=handler;return b;}
function refresh(payload){
  state.doc=payload.project;state.rev=payload.revision;
  el("undo").disabled=!payload.undo;el("redo").disabled=!payload.redo;
  if(state.scene>=state.doc.scenes.length)state.scene=0;
  if(state.actor>=(scene()?.actors.length||0))state.actor=-1;
  if(state.clip>=(actor()?.actions.length||0))state.clip=-1;
  el("projectInfo").textContent=state.doc.title+" · "+state.doc.canvas.join("×")+" · "+state.doc.fps+"fps";
  showSidebar();showScene();notice("Saved locally");
}
function showSidebar(){
  const scenes=el("scenes");scenes.replaceChildren();
  state.doc.scenes.forEach((s,i)=>scenes.append(button(s.id+" · "+s.frames+" frames",i===state.scene,()=>{stop();state.scene=i;state.actor=-1;state.clip=-1;state.frame=0;showSidebar();showScene();})));
  if(!state.doc.scenes.length)scenes.textContent="Create a scene to start.";
  const actors=el("actors");actors.replaceChildren();
  (scene()?.actors||[]).forEach((a,i)=>actors.append(button(a.id+" · "+a.character,i===state.actor,()=>{state.actor=i;state.clip=-1;showSidebar();showScene();})));
  if(!scene()?.actors.length)actors.textContent="Import a rig and place a character.";
  el("assets").textContent=Object.entries(state.doc.assets).map(pair=>pair[0]+" · "+pair[1].kind+" · "+pair[1].license).join("\n")||"No imported artwork";
  el("assets").style.whiteSpace="pre-line";
  showMotions();
}
function showMotions(){
  const holder=el("motions");holder.replaceChildren();
  const filter=el("searchMotions").value.toLowerCase();
  const available=[
    ...Object.keys(state.doc.motion_library.clips).map(id=>({kind:"keyframed",id})),
    ...Object.keys(state.doc.motion_library.poses).map(id=>({kind:"pose",id}))
  ];
  available.filter(item=>item.id.toLowerCase().includes(filter)).forEach(item=>{
    const key=item.kind+":"+item.id;
    holder.append(button(item.id+" · "+item.kind,key===state.motion,()=>{state.motion=key;showMotions();}));
  });
  if(!holder.children.length)holder.textContent="No matching clips. Import a motion JSON.";
  el("addClip").disabled=!state.motion||!actor();
}
function showScene(){
  const s=scene();el("sceneTitle").textContent=s?s.id:"Create your first scene";
  el("scrub").max=String(Math.max(0,(s?.frames||1)-1));
  state.frame=Math.min(state.frame,Number(el("scrub").max));el("scrub").value=String(state.frame);
  el("timeCode").textContent=s?(state.frame/state.doc.fps).toFixed(3)+" s · "+state.frame:"0.000 s";
  const img=el("frameImage");
  if(s){
    const url="/api/frame?scene="+encodeURIComponent(s.id)+"&index="+state.frame+"&mode="+state.mode;
    img.src=url;
    el("exportFrame").href=url;el("exportFrame").download=s.id+"_"+state.frame+".png";
    el("frameError").hidden=true;
  }else{
    img.removeAttribute("src");el("frameError").hidden=false;el("frameError").textContent="Add a scene and imported character rig.";
  }
  showInspector();showTracks();
}
function showTracks(){
  const holder=el("trackRows");holder.replaceChildren();
  if(!actor()){holder.textContent="Select an actor to edit its animation timeline.";return;}
  if(!actor().actions.length)holder.textContent="Choose a reusable motion and add a clip.";
  actor().actions.forEach((clip,i)=>{
    const row=document.createElement("div");row.className="track";
    const name=button((clip.source||clip.clip)+" · "+clip.clip,i===state.clip,()=>{state.clip=i;showTracks();showInspector();});
    const time=document.createElement("span");time.className="time";time.textContent=clip.start_frame+"–"+clip.end_frame;
    row.append(name,time);holder.append(row);
  });
}
function showInspector(){
  const a=actor();
  el("inspectorEmpty").hidden=!!a;el("actorInspector").hidden=!a;el("clipInspector").hidden=!a?.actions[state.clip];
  if(!a)return;
  el("selectedActor").textContent=a.id+" · "+a.character;
  el("actorX").value=a.position[0];el("actorY").value=a.position[1];el("actorScale").value=a.scale;
  const c=a.actions[state.clip];if(c){el("selectedClip").textContent=c.source||c.clip;el("clipStart").value=c.start_frame;el("clipEnd").value=c.end_frame;}
}
async function edit(command){
  const response=await get("/api/edit",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision:state.rev,command})});
  refresh(response);
}
async function history(kind){
  const response=await get("/api/"+kind,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({revision:state.rev})});
  refresh(response);
}
function stop(){if(state.timer)clearInterval(state.timer);state.timer=null;el("play").textContent="▶ Preview";}
function safe(handler){return ()=>Promise.resolve().then(handler).catch(e=>notice(e.message,true));}
el("frameImage").addEventListener("error",()=>{el("frameError").hidden=false;el("frameError").textContent="Renderer could not load this frame. Check actual rig assets or use schematic mode.";notice("Frame render error; no hidden fallback.",true);});
el("scrub").oninput=()=>{state.frame=Number(el("scrub").value);showScene();};
el("renderMode").onchange=()=>{state.mode=el("renderMode").value;showScene();};
el("searchMotions").oninput=showMotions;
el("play").onclick=()=>{if(state.timer){stop();return;}if(!scene())return;el("play").textContent="■ Pause";state.timer=setInterval(()=>{const s=scene();if(!s){stop();return;}state.frame=(state.frame+1)%s.frames;showScene();},Math.max(110,1000/state.doc.fps));};
el("undo").onclick=safe(()=>history("undo"));el("redo").onclick=safe(()=>history("redo"));
el("saveActor").onclick=safe(()=>edit({op:"batch",commands:[
  {op:"set",path:"/scenes/"+state.scene+"/actors/"+state.actor+"/position",value:[Number(el("actorX").value),Number(el("actorY").value)]},
  {op:"set",path:"/scenes/"+state.scene+"/actors/"+state.actor+"/scale",value:Number(el("actorScale").value)}
]}));
el("saveClip").onclick=safe(()=>edit({op:"batch",commands:[
  {op:"set",path:"/scenes/"+state.scene+"/actors/"+state.actor+"/actions/"+state.clip+"/start_frame",value:Number(el("clipStart").value)},
  {op:"set",path:"/scenes/"+state.scene+"/actors/"+state.actor+"/actions/"+state.clip+"/end_frame",value:Number(el("clipEnd").value)}
]}));
el("removeClip").onclick=safe(async()=>{await edit({op:"remove",path:"/scenes/"+state.scene+"/actors/"+state.actor+"/actions/"+state.clip});state.clip=-1;showScene();});
el("addClip").onclick=safe(async()=>{
  if(!actor()||!state.motion)throw Error("Select an actor and motion");
  const a=actor(),s=scene(),parts=state.motion.split(":"),kind=parts[0],source=parts[1];
  const duration=kind==="pose"?state.doc.fps:Math.round(state.doc.motion_library.clips[source].duration*state.doc.fps);
  const start=Math.min(state.frame,s.frames-1),end=Math.min(s.frames,start+Math.max(1,duration));
  const ids=new Set(a.actions.map(c=>c.id));let n=1;while(ids.has("motion_"+n))n++;
  const index=a.actions.length;
  await edit({op:"add",path:"/scenes/"+state.scene+"/actors/"+state.actor+"/actions/-",
    value:{id:"motion_"+n,clip:kind,source,start_frame:start,end_frame:end}});
  state.clip=index;showScene();
});
el("newScene").onclick=safe(async()=>{
  const id=prompt("Unique scene ID:","scene_"+(state.doc.scenes.length+1));if(!id)return;
  const frames=Number(prompt("Scene frames:",String(state.doc.fps*2)));
  const index=state.doc.scenes.length,c=state.doc.canvas;
  await edit({op:"add",path:"/scenes/-",value:{id,frames,camera:{center:[c[0]/2,c[1]/2],zoom:1},actors:[],props:[],dialogue:[]}});
  state.scene=index;state.actor=-1;state.clip=-1;state.frame=0;showSidebar();showScene();
});
el("newActor").onclick=safe(async()=>{
  if(!scene())throw Error("Create a scene first");
  const chars=Object.keys(state.doc.characters);if(!chars.length)throw Error("Import a compatible 15-part rig with the CLI first");
  const character=prompt("Choose registered character: "+chars.join(", "),chars[0]);if(!character)return;
  const id=prompt("Unique actor instance ID:",character);if(!id)return;
  const index=scene().actors.length,c=state.doc.canvas;
  await edit({op:"add",path:"/scenes/"+state.scene+"/actors/-",value:{
    id,character,position:[c[0]/2,c[1]*.65],scale:.6,depth:100,actions:[]}});
  state.actor=index;state.clip=-1;showSidebar();showScene();
});
get("/api/project").then(refresh).catch(e=>notice(e.message,true));
