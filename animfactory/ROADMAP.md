# Independent AnimFactory platform — dependency-ordered implementation ledger

The product is NOT Episode 03. Episode 03 is a future compatibility/visual
acceptance source, never the default project format or cast registry. Protect
existing 2D art, FFmpeg, motion tests, voice and schematic previews. Neither
create a new overall license nor silently switch renderer/provider.

## Audit baseline (verified before milestone 1)

- [x] Inspect latest main, branches and PR #3. Four historical branches and
  the old work branch were found. PR #3 merged after its required checks passed,
  as explicitly authorized by the owner: merge SHA 128094bb04796ecc89f5ec89e3eef6403a3b57a3.
- [x] Reuse original two-bone IK, PNG rig format and Pillow/FFmpeg.
- [x] Reuse PR #3's JSON keyframed clip library, named poses, camera curves,
  foot-plant QA, prop ownership/depth and real screenshot tests.
- [x] Read existing 15s baseline renderer benchmarks; neither synthetic
  Godot nor schematic Pygame-ce A/B justifies a production migration.
- [x] Preserve the existing PySpine copyright notice; no copyleft source
  imported and no new overall product license assigned.

## Milestone 1: standalone product data and save/edit boundary (this PR)

- [x] Version 1 independent project format with strict cross-references,
  frame-accurate timelines and explicit schema/version migration gate.
- [x] Self-contained rig/PNG imports with hashes, art rights/source metadata,
  canonical 15-bone compatibility and no destructive overwrite.
- [x] Product-owned snapshot of reusable named clips and poses; two distinct
  characters can use one source without duplicated animation Python.
- [x] Product-to-existing-renderer adapter, project-scoped keyframed motion,
  accurate integer-frame time conversion, no Episode03 shot assumptions.
- [x] Transactional timeline edit commands, atomic disk save, bounded
  in-session undo and redo, stale-browser-revision rejection.
- [x] Local accessible studio MVP: scene/asset/motion listing, actor placement,
  timeline clip selection/timing, frame preview and PNG export.
- [x] Python CLI and short technical FFmpeg export with FFprobe verification;
  no paid inference service, full movie or silently synthetic voices.
- [x] Regression tests: two independent rigs, shared clip, project save/load,
  corrupted art, unsafe paths, bad commands, HTTP studio, tiny actual MP4.
- [ ] Broader generic 3D-like rig graph/retargeting and cross-project semantic
  motion library registry; existing 15-bone format is current compatibility gate.
- [ ] Hosted authentication and resource isolation; local server only.

## Milestone 2: artwork/rig preparation (issue #5; first focused PR)

- [x] Browser drag/drop import of all 15 separate transparent PNG body-part
  layers with semantic naming, alpha/image dimension validation, thumbnail
  review, SHA checks, source/rights metadata and no original-art overwrite.
- [x] Native Canvas **source pivot and bone-end drag handles**, limb draw
  depth/mirror controls, fixed anatomical joint anchors, editable arm/leg
  lengths and a real Pillow/IK assembled character/reach preview.
- [x] Immutable content-hashed rig JSON revisions with restore, atomic
  project pointer switching and in-session undo/redo.
- [x] Synthetic technical fixture tests for layer import, source integrity,
  rig revision save/load, Pillow pivot effects and studio API security.
- [ ] Custom parent-child bone hierarchy, per-bone rotation limits, full
  deformable mesh editor and GUI joint limits: the existing 15-bone roles
  remain fixed. See issue #8.
- [ ] Safe in-place artwork replacement/reimport versioning (as distinct
  from immutable geometry-only rig revisions). Current import requires a
  new character ID and keeps originals unchanged.
- [ ] Multi-format review: PSD layer parser, SVG raster adapter (license and
  script sanitization), image metadata/provenance and artwork hash index.
- [ ] Optional rembg segmentation adapter with license/weight analysis,
  explicit opt-in and per-stage ability to edit. SAM2 only after weight and
  inference costs are verified. Neither invent occluded anatomy nor send
  user assets off-machine without explicit permission.
- [ ] Optional Rigby2D import mapping after actual source/API audit.

## Milestone 3: scalable animation authoring and registry

- [x] Browser keyframed clip authoring (issue #6): create/duplicate named
  reusable sources, drag normalized key points, add/remove channels and keys,
  choose smooth/linear/step, duration and loop flag, save via existing versioned
  JSON validation. Two compatible imported rigs reuse the SAME authored clip;
  tests cover real IK frames, persistence, undo/redo and invalid curves.
- [ ] Curve playback still uses original ActionMixer, but a rich multilayer
  state-machine/retarget-mask editor is not complete (issue #7).
- [ ] Rig hierarchy and explicit parent/child transforms beyond existing
  15-bone compatibility; reusable retarget maps and joint constraints.
- [ ] Animation layering/masks, state transitions, planted-foot diagnostics
  and global motion registry with semantic tags/search/previews.
- [ ] Production-reviewed reusable complex actions: pour, stir, eat, cook,
  carry, sit, speak; per-clip QA and hand-contact acceptance.
- [ ] Face/eye/blink/emotion blend shapes, multiple viseme sets, reliable
  hand-to-prop gripping and collision-aware interaction when justified.
- [ ] Secondary motion for clothing/hair, optional deterministic physics.
- [ ] Full-featured rotation/parenting/keyframe timeline editor; native Canvas
  already handles image pivots. Konva was researched (MIT, maintained) but
  is not imported before an actual feature/cost comparison (issues #6/#8).

## Milestone 4: hosted studio and stable API

- [ ] Evaluate Konva under its actual maintained license and browser support,
  avoiding competing canvas stacks.
- [ ] Optional FastAPI deployment with authentication, CSRF, rate limits,
  per-project file boundaries, valid CSP, background jobs and cancellation.
- [ ] Hosted asset library/rig browser/keyframe editor, previews, camera,
  shared-state inspector and version migrations; avoid desktop software.
- [ ] HTTP/Python/CLI API stability policy, tests and OpenAPI documentation.

## Milestone 5: independent provider adapters (opt-in only)

- [ ] Provider registry with strict capabilities, opaque asset handles,
  network/secret permission boundaries, costs and retry/timeout/cancellation.
- [ ] At most one primary opt-in service per capability: artwork (ComfyUI),
  segmentation (rembg or SAM2), rig edit (Rigby2D), sound (existing Kokoro +
  Rhubarb), CPU render (GitHub Actions), optional object storage/cloud GPU.
- [ ] Real upstream source/license/model-weight/SDK and service-cost audit
  BEFORE enabling a provider. No paid API or GPU activation without approval.
- [ ] Projects remain playable/renderable offline even if providers vanish.

## Milestone 6: performance and quality at scale

- [ ] Content-addressed rig/clip/asset caches shared across projects.
- [ ] Incremental previews, resumable chunks and worker limits using existing
  GitHub workflows, with cancellation and input hashes.
- [ ] Short smoke by default; full 1080p user-authorized render only on demand.
- [ ] Benchmark cost, peak memory, FFmpeg decode, per-frame contact and
  visual/creative review against exact same art, timing and frames.
- [ ] Deterministic non-AI route for every edit, optional validated NL→JSON
  inference without executing untrusted model output.

## Acceptance milestones

**M1 technical:** brand-new project, import compatible rig, select shared named
clip, edit frame/actor in browser, undo/redo, save/reload, preview and export a
tiny valid H.264 movie; second compatible rig uses the SAME clip. Product works
offline with no model calls. All tests pass on both Python 3.11 and 3.12.

**M2 creative software:** artist can import layered art, adjust every pivot,
assign rig, animate a custom bone/face clip, save and reuse from browser with
actual production sprites. This is NOT yet implemented by M1.

**M3 public deployment:** authenticated multi-user browser studio, secure
storage, provider permissions and cancellation. Loopback M1 studio alone does
NOT meet production SaaS readiness.

**Film-level release:** complete reviewed acting/voice/visual fidelity required;
passing tests or a schematic 15-second benchmark never meets this gate.
