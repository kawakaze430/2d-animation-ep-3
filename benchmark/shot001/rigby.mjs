#!/usr/bin/env node
// MIT OR Apache-2.0 upstream Rigby2D remains external; do not vendor/fork its code.
// This driver creates real .rigby skeletal projects with reference-matched part images,
// and invokes Rigby2D's export_sprite_sheet MCP tool handler with format='frames'.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { pathToFileURL } from 'node:url';

const [stageFile, rigbyRoot, outputArg] = process.argv.slice(2);
if (!stageFile || !rigbyRoot || !outputArg) {
  throw new Error('Usage: node rigby.mjs rigby_stage.json /path/to/rigby2d build/shot001/rigby');
}
const outputRoot = path.resolve(outputArg);
const imports = async (file) => import(pathToFileURL(path.resolve(rigbyRoot, file)).href);
const { Skeleton, makeBone, makeSlot, makeAttachment } = await imports('src/core/model.js');
const { transform } = await imports('src/core/math.js');
const { Animation, setKey } = await imports('src/core/animation.js');
const { zip } = await imports('src/editor/zip.js');
const { framesBounds } = await imports('src/editor/spritesheet.js');
const { createTools, Workspace } = await imports('src/mcp/tools.js');

const stage = JSON.parse(await fs.readFile(stageFile, 'utf8'));
if (stage.shot !== 'SHOT_001' || stage.fps !== 24 || stage.duration !== 15 ||
    stage.cast.join(',') !== 'DAN,MAYA,NINA') {
  throw new Error('Rigby stage does not match locked Episode 03 SHOT_001');
}
await fs.mkdir(outputRoot, { recursive: true });
const framesDir = path.join(outputRoot, 'frames');
await fs.mkdir(framesDir, { recursive: true });
const ws = await Workspace.open([path.resolve(outputRoot)]);
const exporter = createTools(ws).find(t => t.name === 'export_sprite_sheet');
if (!exporter) throw new Error('Pinned Rigby2D has no MCP export_sprite_sheet tool');
const outputs = {};
for (const id of stage.cast) {
  const started = performance.now();
  const actor = stage.actors[id];
  const doc = new Skeleton();
  doc.name = 'Episode03_SHOT_001_' + id;
  doc.workspace = 'film';
  doc.settings.fps = 24;
  doc.settings.width = 1920;
  doc.settings.height = 1080;
  doc.settings.background = null;
  const animation = new Animation('SHOT_001', 15);
  doc.animations.push(animation);
  const images = new Map();
  let hasBoneMotion = false;
  // Genuine parent/child skeleton: shoulder -> upper arm -> forearm -> hand,
  // hip -> thigh -> shin -> foot, head -> torso -> pelvis. Inherited scale is
  // compensated by relative keys so the source PNG pivot remains aligned.
  const parentBone = (bone) => {
    if (bone === 'pelvis') return null;
    if (bone === 'torso') return 'pelvis';
    if (bone === 'head' || bone.startsWith('upper_arm.')) return 'torso';
    if (bone.startsWith('thigh.')) return 'pelvis';
    if (bone.startsWith('forearm.')) return bone.replace('forearm.', 'upper_arm.');
    if (bone.startsWith('hand.')) return bone.replace('hand.', 'forearm.');
    if (bone.startsWith('shin.')) return bone.replace('shin.', 'thigh.');
    if (bone.startsWith('foot.')) return bone.replace('foot.', 'shin.');
    throw new Error('Unknown cast bone: ' + bone);
  };
  const byBone = new Map();
  for (const part of actor.parts) {
    if (byBone.has(part.bone)) throw new Error(id + ': duplicate source bone ' + part.bone);
    byBone.set(part.bone, part);
  }
  const boneIndex = new Map();
  const pending = new Set(actor.parts.map(p => p.bone));
  while (pending.size) {
    let progressed = false;
    for (const part of actor.parts) {
      if (!pending.has(part.bone)) continue;
      const parent = parentBone(part.bone);
      if (parent && !boneIndex.has(parent)) continue;
      boneIndex.set(part.bone, doc.bones.length);
      doc.bones.push(makeBone(part.id, parent ? boneIndex.get(parent) : 0,
                              transform(0, 0, 0), 1));
      pending.delete(part.bone);
      progressed = true;
    }
    if (!progressed) throw new Error(id + ': invalid bone hierarchy');
  }
  for (const part of [...actor.parts].sort((a,b) => a.depth-b.depth)) {
    const i = boneIndex.get(part.bone);
    const p = part.pivot;
    const offset = transform(part.width / 2 - p[0], p[1] - part.height / 2);
    const imageId = part.image.replace(/\.png$/i, '');
    const att = makeAttachment('base', imageId, offset, part.width, part.height);
    const slot = makeSlot('slot_' + part.id, i, att);
    doc.slots.push(slot);
    doc.images.push({ name: imageId, path: null, width: part.width, height: part.height });
    images.set(imageId, await fs.readFile(path.join(path.dirname(stageFile), part.image)));
    const tl = animation.boneTimelineMut(i);
    const parent = parentBone(part.bone);
    for (let k = 0; k < part.frames.length; k++) {
      let [t, x, y, degrees, factor] = part.frames[k];
      if (parent) {
        const parentPart = byBone.get(parent);
        const [, px, py, pr, ps] = parentPart.frames[k];
        if (!(ps > 0)) throw new Error(id + ': invalid parent skeleton scale');
        const rad = -pr * Math.PI / 180;
        const dx = x - px, dy = y - py;
        [x, y] = [(Math.cos(rad)*dx - Math.sin(rad)*dy)/ps,
                  (Math.sin(rad)*dx + Math.cos(rad)*dy)/ps];
        degrees -= pr;
        factor /= ps;
      }
      setKey(tl.translate, t, [x, y]);
      setKey(tl.rotate, t, degrees);
      setKey(tl.scale, t, [factor, factor]);
      if (t > 0) hasBoneMotion = true;
    }
    if (part.bone === 'head') {
      const slotIndex = doc.slots.length - 1;
      slot.attachments[0].name = 'X';
      slot.attachment = 'X';
      for (const [shape, face] of Object.entries(actor.faces)) {
        const faceId = face.image.replace(/\.png$/i, '');
        const a = makeAttachment(shape, faceId,
          transform(face.width / 2 - p[0], p[1] - face.height / 2),
          face.width, face.height);
        slot.attachments.push(a);
        doc.images.push({ name: faceId, path: null, width: face.width, height: face.height });
        images.set(faceId, await fs.readFile(path.join(path.dirname(stageFile), face.image)));
      }
      const slotTl = animation.slotTimelineMut(slotIndex);
      for (const [t, shape] of actor.mouth_keys) {
        if (!slot.attachments.some(a => a.name === shape)) {
          throw new Error(id + ': missing original mouth artwork for cue ' + shape);
        }
        setKey(slotTl.attachment, t, shape);
      }
    }
  }
  if (doc.bones.length < 16 || !hasBoneMotion) throw new Error(id + ': invalid skeletal part rig');
  const error = doc.validate();
  if (error) throw new Error(id + ': Rigby2D model validation: ' + error);

  const entries = [
    { path: 'project.json', bytes: new TextEncoder().encode(doc.toJson()) },
    ...[...images].map(([key, bytes]) => ({ path: 'images/' + key + '.png', bytes })),
  ];
  const rigFile = path.join(outputRoot, id + '.rigby');
  await fs.writeFile(rigFile, zip(entries));
  const rigBuildMs = performance.now() - started;

  // Origin offset computed from the very SAME Rigby runtime bounds as the MCP
  // exporter uses. Rigby's Y-up coordinate needs converting for Pillow Y-down.
  const bounds = framesBounds(doc, ['SHOT_001'], { fps:24, loop:true, scale:1 });
  if (!bounds) throw new Error(id + ': Rigby rendered no visible skeleton geometry');
  const x0 = Math.floor(bounds[0] - 2);
  const y1 = Math.ceil(bounds[3] + 2);
  const origin = [-x0, y1];
  const expectedWidth = Math.ceil(bounds[2] - bounds[0]) + 4;
  const expectedHeight = Math.ceil(bounds[3] - bounds[1]) + 4;

  const renderStart = performance.now();
  const result = await exporter.handler({
    input: rigFile,
    output_folder: framesDir,
    name: id,
    format: 'frames',
    animations: ['SHOT_001'],
    fps: 24,
    scale: 1,
    loop: true,
    overwrite: false,
  });
  const exportMs = performance.now() - renderStart;
  if (result.frames !== 360 || result.width !== expectedWidth || result.height !== expectedHeight) {
    throw new Error(id + ': Rigby frame count/size differs from expected runtime bounds');
  }
  const rendered = path.join(framesDir, id);
  const filenames = (await fs.readdir(rendered)).filter(x => x.endsWith('.png')).sort();
  if (filenames.length !== 360) throw new Error(id + ': expected 360 Rigby PNG frames');
  const hashes = await Promise.all([0, 60, 180, 300, 359].map(async i =>
    crypto.createHash('sha256').update(await fs.readFile(path.join(rendered, filenames[i]))).digest('hex')));
  if (new Set(hashes).size < 2) throw new Error(id + ': no movement detected in Rigby frames');
  outputs[id] = {
    engine: 'Rigby2D (official software renderer via MCP export_sprite_sheet)',
    file: rigFile,
    frames_folder: rendered,
    frame_pattern: 'SHOT_001_%03d.png',
    origin_px: origin,
    actor_world_origin: actor.origin,
    frames: filenames.length,
    width: result.width,
    height: result.height,
    frame_sha256_samples: hashes,
    rig_build_seconds: rigBuildMs / 1000,
    rigby_character_export_seconds: exportMs / 1000,
    cpu_user_microseconds: process.resourceUsage().userCPUTime,
    cpu_system_microseconds: process.resourceUsage().systemCPUTime,
    rss_bytes_after_export: process.memoryUsage().rss,
    rig_structure: { bones:doc.bones.length, slots:doc.slots.length, animations:doc.animations.length },
  };
  console.log(id, JSON.stringify({frameCount: result.frames, rigBuildMs, exportMs}));
}
const meta = {
  shot: 'SHOT_001', fps:24, duration:15, cast:stage.cast,
  source: 'Rigby2D MCP tool handler; real rendered RGBA PNG frames',
  rigby_source_commit: process.env.RIGBY_SHA ?? 'UNPINNED',
  actors:outputs,
};
await fs.writeFile(path.join(outputRoot, 'export_metadata.json'), JSON.stringify(meta, null, 2)+'\n');
console.log(path.join(outputRoot, 'export_metadata.json'));
