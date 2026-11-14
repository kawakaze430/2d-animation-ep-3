"use strict";
// Rig authoring UI. Actual compositing and IK previews come from the Python renderer.
// This native Canvas is ONLY for source-PNG control-point editing, not an exporter.
const rigRoles = [
  "head","torso","pelvis",
  "upper_arm.left","upper_arm.right","forearm.left","forearm.right",
  "hand.left","hand.right","thigh.left","thigh.right",
  "shin.left","shin.right","foot.left","foot.right"
];
const rigUI = {
  layers:new Map(), urls:[], data:null, character:"", bone:"head",
  sprite:null, transform:null, drag:null, loading:false
};
const rg = id => document.getElementById(id);
function rigMessage(text,error=false){
  rg("rigStatus").textContent=text;
  rg("rigStatus").style.color=error?"#ffaaa7":"#a9e6b4";
}
function rigNormalizedName(name){
  let base=name.toLowerCase().replace(/\.png$/,"").replace(/[\s-]+/g,"_");
  if(base.endsWith("_left")||base.endsWith("_right")){
    base=base.replace(/_(left|right)$/,".$1");
  }
  return rigRoles.includes(base)?base:null;
}
function rigClearPreviews(){
  for(const url of rigUI.urls)URL.revokeObjectURL(url);
  rigUI.urls=[];
}
function rigAddFiles(files){
  for(const file of files){
    const bone=rigNormalizedName(file.name);
    if(!bone || !/\.png$/i.test(file.name)){
      rigMessage("Unrecognized filename "+file.name+". Rename files to match anatomical roles.",true);
      continue;
    }
    if(file.size>4*1024*1024){
      rigMessage(bone+" exceeds the per-layer 4 MB upload limit.",true);
      continue;
    }
    rigUI.layers.set(bone,file);
  }
  rigPaintImport();
}
function rigPaintImport(){
  rigClearPreviews();
  const list=rg("rigImportList");list.replaceChildren();
  for(const bone of rigRoles){
    const item=document.createElement("div");item.className="item";
    const file=rigUI.layers.get(bone);
    if(file){
      const img=document.createElement("img");
      const url=URL.createObjectURL(file);rigUI.urls.push(url);
      img.src=url;img.alt=bone+" layer";
      item.append(img);
    } else item.classList.add("missing");
    const label=document.createElement("span");label.textContent=bone+(file?" ✓":" missing");
    item.append(label);list.append(item);
  }
  const done=rigUI.layers.size===rigRoles.length;
  rg("rigImportSubmit").disabled=!done || rigUI.loading;
  const count=rigUI.layers.size;
  if(!done)rigMessage(count+"/15 PNG body parts mapped. Import requires all 15.");
  else rigMessage("All 15 roles mapped. You can import, then adjust pivots visually.");
}
function rigUpdateCharacters(){
  const selected=rg("rigCharacter");
  const saved=rigUI.character;
  selected.replaceChildren();
  for(const name of Object.keys(state.doc?.characters||{})){
    const option=document.createElement("option");option.value=name;option.textContent=name;
    selected.append(option);
  }
  rigUI.character=Object.hasOwn(state.doc?.characters||{}, saved)
    ?saved : (selected.options[0]?.value||"");
  selected.value=rigUI.character;
}
function rigSelectedPart(){
  return rigUI.data?.rig?.parts?.find(p=>p.bone===rigUI.bone)||null;
}
function rigPartSize(){
  return rigUI.data?.dimensions?.[rigUI.bone]||null;
}
function rigPopulatePart(){
  const part=rigSelectedPart();
  if(!part)return;
  rg("rigBone").value=rigUI.bone;
  rg("rigPivotX").value=part.pivot[0];
  rg("rigPivotY").value=part.pivot[1];
  const end=part.source_end||[part.pivot[0],part.pivot[1]+10];
  rg("rigEndX").value=end[0];rg("rigEndY").value=end[1];
  rg("rigDepth").value=part.depth??0;
  rg("rigMirror").checked=part.mirror===true;
  const size=rigPartSize();
  rg("rigDimensions").textContent=size?size.join(" × ")+" original PNG pixels":"";
  rigUI.sprite=new Image();
  rigUI.sprite.onload=rigPaintCanvas;
  rigUI.sprite.onerror=()=>rigMessage("Cannot load verified PNG source part",true);
  rigUI.sprite.src="/api/rig-image?character="+encodeURIComponent(rigUI.character)
    +"&bone="+encodeURIComponent(rigUI.bone);
}
function rigNumeric(id){
  const value=Number(rg(id).value);
  if(!Number.isFinite(value))throw Error("Rig geometry requires finite numbers");
  return value;
}
function rigPaintCanvas(){
  const image=rigUI.sprite,canvas=rg("rigPartCanvas"),ctx=canvas.getContext("2d");
  if(!image||!image.complete||!image.naturalWidth)return;
  const w=image.naturalWidth,h=image.naturalHeight;
  const scale=Math.min((canvas.width-36)/w,(canvas.height-36)/h);
  const ox=(canvas.width-w*scale)/2,oy=(canvas.height-h*scale)/2;
  rigUI.transform={scale,ox,oy};
  ctx.clearRect(0,0,canvas.width,canvas.height);
  const tile=16;
  for(let y=0;y<canvas.height;y+=tile)for(let x=0;x<canvas.width;x+=tile){
    ctx.fillStyle=(x/tile+y/tile)%2===0?"#35455b":"#28364a";
    ctx.fillRect(x,y,tile,tile);
  }
  ctx.drawImage(image,ox,oy,w*scale,h*scale);
  let start,end;
  try {
    start=[rigNumeric("rigPivotX"),rigNumeric("rigPivotY")];
    end=[rigNumeric("rigEndX"),rigNumeric("rigEndY")];
  }catch{return;}
  const pointToCanvas=p=>[ox+p[0]*scale,oy+p[1]*scale];
  const p=pointToCanvas(start),q=pointToCanvas(end);
  ctx.lineWidth=2;ctx.strokeStyle="#73c8ef";
  ctx.beginPath();ctx.moveTo(...p);ctx.lineTo(...q);ctx.stroke();
  for(const [xy,color,text] of [[p,"#ff726a","Pivot"],[q,"#62ddf0","End"]]){
    ctx.fillStyle=color;ctx.strokeStyle="#162231";ctx.lineWidth=2;
    ctx.beginPath();ctx.arc(...xy,8,0,2*Math.PI);ctx.fill();ctx.stroke();
    ctx.fillStyle="#fff";ctx.font="12px sans-serif";ctx.fillText(text,xy[0]+12,xy[1]-8);
  }
}
function rigCanvasPointer(event){
  const canvas=rg("rigPartCanvas"),rect=canvas.getBoundingClientRect();
  return [(event.clientX-rect.left)*canvas.width/rect.width,
          (event.clientY-rect.top)*canvas.height/rect.height];
}
function rigBeginDrag(event){
  if(!rigUI.transform)return;
  const [x,y]=rigCanvasPointer(event);
  const t=rigUI.transform;
  const start=[rigNumeric("rigPivotX"),rigNumeric("rigPivotY")];
  const end=[rigNumeric("rigEndX"),rigNumeric("rigEndY")];
  const dist=p=>Math.hypot(x-(t.ox+p[0]*t.scale),y-(t.oy+p[1]*t.scale));
  const a=dist(start),b=dist(end);
  rigUI.drag=event.shiftKey?"end":(b<a?"end":"pivot");
  rg("rigPartCanvas").setPointerCapture(event.pointerId);
  rigMoveDrag(event);
}
function rigMoveDrag(event){
  if(!rigUI.drag||!rigUI.transform||!rigPartSize())return;
  const [x,y]=rigCanvasPointer(event),t=rigUI.transform,[w,h]=rigPartSize();
  const clamp=(v,min,max)=>Math.min(max,Math.max(min,v));
  const xx=Math.round(clamp((x-t.ox)/t.scale,-w,2*w)*2)/2;
  const yy=Math.round(clamp((y-t.oy)/t.scale,-h,2*h)*2)/2;
  const key=rigUI.drag==="end"?["rigEndX","rigEndY"]:["rigPivotX","rigPivotY"];
  rg(key[0]).value=xx;rg(key[1]).value=yy;rigPaintCanvas();
}
function rigEndDrag(){rigUI.drag=null;}
function rigPopulateAnatomy(){
  if(!rigUI.data)return;
  const a=rg("rigAnchor").value;
  const defaultAnchors={
    neck:[0,-195],shoulder_left:[-48,-165],shoulder_right:[48,-165],
    hip_left:[-30,30],hip_right:[30,30]
  };
  const v=rigUI.data.rig.anchors?.[a]||defaultAnchors[a];
  rg("rigAnchorX").value=v[0];rg("rigAnchorY").value=v[1];
  const length=rg("rigLength").value;
  const defaults={upper_arm:135,forearm:125,thigh:180,shin:170};
  rg("rigLengthValue").value=rigUI.data.rig.lengths?.[length]??defaults[length];
}
function rigPreview(){
  if(!rigUI.character)return;
  const url="/api/rig-preview?character="+encodeURIComponent(rigUI.character)+
    "&movement="+(rg("rigMovement").checked?"1":"0");
  rg("rigFullImage").src=url;
}
async function rigLoad(){
  rigUpdateCharacters();
  if(!rigUI.character){
    rigUI.data=null;rg("rigWarnings").textContent="No rig imported. Use the 15-part PNG importer.";
    return;
  }
  const payload=await get("/api/rig?character="+encodeURIComponent(rigUI.character));
  rigUI.data=payload.rig;
  const names=rg("rigBone");names.replaceChildren();
  for(const bone of rigRoles){
    const option=document.createElement("option");option.value=bone;option.textContent=bone;
    names.append(option);
  }
  if(!rigRoles.includes(rigUI.bone))rigUI.bone=rigRoles[0];
  const versions=rg("rigVersions");versions.replaceChildren();
  for(const version of rigUI.data.versions){
    const option=document.createElement("option");option.value=version;
    option.textContent=version==="rig.json"?"Original artwork rig":
      "Revision "+version.slice(9,21);
    versions.append(option);
  }
  versions.value=rigUI.data.active_version;
  rg("rigWarnings").textContent=rigUI.data.warnings?.join("\n")||"No detected rig geometry warnings.";
  rigPopulatePart();rigPopulateAnatomy();rigPreview();
}
async function rigMutate(route,fields){
  const response=await get(route,{method:"POST",
    headers:{"Content-Type":"application/json"},
    body:JSON.stringify({revision:state.rev,character:rigUI.character,...fields})
  });
  refresh(response);
  await rigLoad();
  rigMessage("Rig configuration saved; original artwork and prior revisions preserved.");
}
function rigDataUrl(file){
  return new Promise((resolve,reject)=>{
    const reader=new FileReader();
    reader.onerror=()=>reject(Error("Cannot read "+file.name));
    reader.onload=()=>resolve(String(reader.result).split(",")[1]);
    reader.readAsDataURL(file);
  });
}
function rigHandlers(){
  rg("openRigStudio").addEventListener("click",async()=>{
    rg("rigDialog").showModal();
    rigUpdateCharacters();
    try {await rigLoad();}catch(e){rigMessage(e.message,true);}
  });
  rg("rigClose").addEventListener("click",()=>rg("rigDialog").close());
  rg("rigFiles").addEventListener("change",e=>rigAddFiles(e.target.files));
  const drop=rg("rigDropZone");
  drop.addEventListener("dragover",e=>{e.preventDefault();drop.classList.add("dragover");});
  drop.addEventListener("dragleave",()=>drop.classList.remove("dragover"));
  drop.addEventListener("drop",e=>{e.preventDefault();drop.classList.remove("dragover");rigAddFiles(e.dataTransfer.files);});
  drop.addEventListener("keydown",e=>{if(e.key==="Enter")rg("rigFiles").click();});
  rg("rigImportSubmit").addEventListener("click",async()=>{
    if(rigUI.loading)return;
    try{
      const name=rg("rigImportName").value.trim();
      if(!/^[A-Za-z][A-Za-z0-9_]{0,31}$/.test(name))throw Error("Character ID must be letters/numbers/underscore, starting with a letter");
      if(rigUI.layers.size!==15)throw Error("Exactly 15 PNG layers required");
      rigUI.loading=true;rg("rigImportSubmit").disabled=true;
      rigMessage("Validating and importing original PNG artwork…");
      const layers={};
      for(const role of rigRoles)layers[role]=await rigDataUrl(rigUI.layers.get(role));
      const response=await get("/api/rig/import",{method:"POST",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({
          revision:state.rev,character:name,layers,
          source:rg("rigImportSource").value,license:rg("rigImportLicense").value
        })
      });
      refresh(response);rigUI.character=name;await rigLoad();
      rigMessage("All 15 transparent sprites imported and saved with SHA-256 provenance.");
    }catch(e){rigMessage(e.message,true);notice(e.message,true);}
    finally{rigUI.loading=false;rigPaintImport();}
  });
  rg("rigCharacter").addEventListener("change",async()=>{
    rigUI.character=rg("rigCharacter").value;
    rigUI.bone="head";
    try{await rigLoad();}catch(e){rigMessage(e.message,true);}
  });
  rg("rigBone").addEventListener("change",()=>{
    rigUI.bone=rg("rigBone").value;rigPopulatePart();
  });
  rg("rigMovement").addEventListener("change",rigPreview);
  for(const id of ["rigPivotX","rigPivotY","rigEndX","rigEndY"])
    rg(id).addEventListener("input",rigPaintCanvas);
  const canvas=rg("rigPartCanvas");
  canvas.addEventListener("pointerdown",rigBeginDrag);
  canvas.addEventListener("pointermove",rigMoveDrag);
  canvas.addEventListener("pointerup",rigEndDrag);
  canvas.addEventListener("pointercancel",rigEndDrag);
  rg("rigSavePart").addEventListener("click",async()=>{
    try {
      await rigMutate("/api/rig/edit",{edit:{kind:"part",bone:rigUI.bone,changes:{
        pivot:[rigNumeric("rigPivotX"),rigNumeric("rigPivotY")],
        source_end:[rigNumeric("rigEndX"),rigNumeric("rigEndY")],
        depth:rigNumeric("rigDepth"),mirror:rg("rigMirror").checked
      }}});
    }catch(e){rigMessage(e.message,true);}
  });
  rg("rigAnchor").addEventListener("change",rigPopulateAnatomy);
  rg("rigLength").addEventListener("change",rigPopulateAnatomy);
  rg("rigSaveAnchor").addEventListener("click",async()=>{
    try{await rigMutate("/api/rig/edit",{edit:{
      kind:"anchor",name:rg("rigAnchor").value,
      value:[rigNumeric("rigAnchorX"),rigNumeric("rigAnchorY")]
    }});}catch(e){rigMessage(e.message,true);}
  });
  rg("rigSaveLength").addEventListener("click",async()=>{
    try{await rigMutate("/api/rig/edit",{edit:{
      kind:"length",name:rg("rigLength").value,value:rigNumeric("rigLengthValue")
    }});}catch(e){rigMessage(e.message,true);}
  });
  rg("rigRestore").addEventListener("click",async()=>{
    try{await rigMutate("/api/rig/restore",{version:rg("rigVersions").value});}
    catch(e){rigMessage(e.message,true);}
  });
  window.addEventListener("animfactory:project-updated",()=>{
    if(rg("rigDialog").open)rigLoad().catch(e=>rigMessage(e.message,true));
  });
  rg("rigFullImage").addEventListener("error",()=>rigMessage("Saved rig could not be rendered; check technical QA.",true));
}
rigHandlers();
