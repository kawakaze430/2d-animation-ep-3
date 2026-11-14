#!/usr/bin/env node
// Headless Rigby smoke ONLY. Synthetic test art must never be called Episode03 production.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { pathToFileURL } from 'node:url';

const [rigbyArg, outArg] = process.argv.slice(2);
if (!rigbyArg || !outArg) throw new Error('usage: node smoke.mjs /rigby/checkout /output');
const out = path.resolve(outArg);
const imported = async (p) => import(pathToFileURL(path.resolve(rigbyArg, p)).href);
const { Skeleton, makeBone, makeSlot, makeAttachment } = await imported('src/core/model.js');
const { transform } = await imported('src/core/math.js');
const { Animation, setKey } = await imported('src/core/animation.js');
const { encodePng } = await imported('src/mcp/png.js');
const { zip } = await imported('src/editor/zip.js');
const { createTools, Workspace } = await imported('src/mcp/tools.js');

await fs.mkdir(out, {recursive:true});
await fs.mkdir(path.join(out, 'frames'), {recursive:true});
const bytes = new Uint8Array(24 * 72 * 4);
for (let y=0;y<72;y++) for (let x=0;x<24;x++) {
  const i=(y*24+x)*4;
  bytes[i]=228; bytes[i+1]=96; bytes[i+2]=54;
  bytes[i+3]=x>2 && x<21 && y>2 && y<69 ? 255 : 0;
}
const png = encodePng({width:24,height:72,data:bytes});
const rig = new Skeleton();
rig.name='Headless-export-smoke-NOT-EPISODE-03';
rig.bones.push(makeBone('test_arm', 0, transform(), 72));
rig.slots.push(makeSlot('arm_slot', 1, makeAttachment('arm', 'arm', transform(0, -36),24,72)));
rig.images.push({name:'arm',path:null,width:24,height:72});
const anim=new Animation('swing',0.5);
const tl=anim.boneTimelineMut(1);
setKey(tl.rotate,0,-30);
setKey(tl.rotate,0.25,30);
setKey(tl.rotate,0.5,-30);
rig.animations.push(anim);
if (rig.validate()) throw new Error(rig.validate());
const file=path.join(out,'smoke.rigby');
await fs.writeFile(file,zip([
  {path:'project.json',bytes:new TextEncoder().encode(rig.toJson())},
  {path:'images/arm.png',bytes:png},
]));
const ws=await Workspace.open([out]);
const exporter=createTools(ws).find(x=>x.name==='export_sprite_sheet');
if(!exporter) throw new Error('Rigby MCP tool is missing');
const start=performance.now();
const result=await exporter.handler({
  input:file,output_folder:path.join(out,'frames'),name:'smoke',
  animations:['swing'],format:'frames',fps:24,loop:true
});
const elapsed=(performance.now()-start)/1000;
if(result.frames!==12) throw new Error('Expected 12 REAL Rigby software-rendered frames');
const dir=path.join(out,'frames','smoke');
const names=(await fs.readdir(dir)).filter(f=>f.endsWith('.png')).sort();
if(names.length!==12)throw new Error('Expected 12 PNG files');
const hashes=await Promise.all([names[0],names[6]].map(async p=>crypto.createHash('sha256').update(await fs.readFile(path.join(dir,p))).digest('hex')));
if(hashes[0]===hashes[1])throw new Error('No skeletal motion detected in Rigby-exported PNGs');
const report={status:'RIGBY_HEADLESS_EXPORT_PASSED__SYNTHETIC_SMOKE_ONLY',
  is_episode03:false,source_sha:process.env.RIGBY_SHA??null,
  engine:'official Rigby2D MCP export_sprite_sheet(format=frames)',
  fps:24,frames:12,render_seconds:elapsed,frame_sha256_samples:hashes,
  node:process.version,rss_bytes:process.memoryUsage().rss,
  cpu:process.resourceUsage()};
await fs.writeFile(path.join(out,'smoke-report.json'),JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify(report));
