/* Browser review uses only text nodes for manifest content. */
(() => {
  'use strict';
  const manifest = window.EPISODE_PREVIEW;
  const $ = id => document.getElementById(id);
  if (!manifest || !Array.isArray(manifest.shots) || !manifest.shots.length) {
    $('shot-title').textContent = 'No review manifest available';
    return;
  }
  const shots = manifest.shots;
  const preview = manifest._preview || {};
  const isStatic = Boolean(preview.static);
  const assetURLs = preview.asset_urls || {};
  let selected = shots[0], playing = false, animationTimer, requestId = 0, blobURL;
  let currentTime = 0;
  const duration = shot => Number(shot.duration || 15);
  const cast = shot => shot.cast || shot.visible_cast || [];
  const title = shot => shot.title || shot.beat || shot.id;
  const locationName = value => String(value || 'HOME_KITCHEN').replaceAll('_', ' ');
  const node = (tag, text, className) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (className) n.className = className; return n; };
  const clear = element => element.replaceChildren();
  $('totals').textContent = `${shots.length} shots · ${(shots.reduce((sum, shot) => sum + duration(shot), 0) / 60).toFixed(0)} minutes · 15 seconds per shot`;
  $('notice').textContent = `${preview.notice || ''} Picture review; performed voices are not included.`;
  $('mode').textContent = `${String(preview.mode || 'blocking').toUpperCase()} REVIEW`;
  $('stage-badge').textContent = `${String(preview.mode || 'blocking').toUpperCase()} · ${isStatic ? '3 SAMPLES' : 'LIVE FRAME'}`;
  $('play').textContent = isStatic ? 'Next sample' : 'Play scene';
  for (const name of [...new Set(shots.flatMap(cast))].sort()) $('cast-filter').append(node('option', name));
  for (const place of [...new Set(shots.map(s => s.location))].filter(Boolean).sort()) {
    const option = node('option', locationName(place)); option.value = place; $('location-filter').append(option);
  }
  function renderLibrary() {
    const query = $('search').value.toLowerCase(), who = $('cast-filter').value, place = $('location-filter').value;
    const shown = shots.filter(s => (!who || cast(s).includes(who)) && (!place || s.location === place) && JSON.stringify(s).toLowerCase().includes(query));
    clear($('shots'));
    $('filtered-count').textContent = `${shown.length} / ${shots.length}`;
    for (const shot of shown) {
      const button = node('button', undefined, `shot-button${shot.id === selected.id ? ' active' : ''}`);
      button.type = 'button'; button.setAttribute('aria-current', shot.id === selected.id ? 'true' : 'false');
      button.append(node('span', String(shots.indexOf(shot) + 1).padStart(3, '0'), 'shot-index'));
      const copy = node('span', undefined, 'shot-copy');
      copy.append(node('strong', title(shot)), node('small', `${cast(shot).join(' · ')} · ${duration(shot)}s`));
      button.append(copy); button.addEventListener('click', () => select(shot)); $('shots').append(button);
    }
    if (!shown.length) $('shots').append(node('p', 'No shots match these filters.', 'empty'));
  }
  function showState(target, value, description) {
    clear(target);
    if (description) target.append(node('p', description));
    if (typeof value === 'string') { target.append(node('p', value)); return; }
    if (!value || typeof value !== 'object') { target.append(node('p', 'Not specified in this draft.')); return; }
    const ledger = node('details', undefined, 'ledger');
    ledger.append(node('summary', 'Continuity ledger'));
    for (const [key, item] of Object.entries(value)) {
      const row = node('div', undefined, 'state-line');
      row.append(node('strong', `${key.replaceAll('_', ' ')}: `), document.createTextNode(typeof item === 'object' ? JSON.stringify(item) : String(item)));
      ledger.append(row);
    }
    target.append(ledger);
  }
  function findImage(value) {
    if (typeof value === 'string' && assetURLs[value]) return assetURLs[value];
    if (Array.isArray(value)) { for (const item of value) { const found = findImage(item); if (found) return found; } }
    if (value && typeof value === 'object') {
      // Prefer the original portrait or sheet to an unapproved sprite layer.
      for (const key of ['portrait', 'reference', 'reference_image', 'sheet', 'reference_sheet', ...Object.keys(value)]) {
        if (key in value) { const found = findImage(value[key]); if (found) return found; }
      }
    }
    return null;
  }
  function references() {
    clear($('references'));
    for (const name of cast(selected)) {
      const record = (manifest.characters || {})[name];
      const imageURL = findImage(record);
      if (!imageURL) continue;
      const link = node('a', undefined, 'reference'); link.href = imageURL; link.target = '_blank'; link.rel = 'noopener';
      const image = node('img'); image.src = imageURL; image.alt = `${name} original identity reference`;
      link.append(image, node('span', name)); $('references').append(link);
    }
    if (!$('references').children.length) $('references').append(node('p', 'No original character images were declared in this manifest.', 'muted'));
  }
  async function displayFrame(time) {
    currentTime = Math.min(Math.max(time, 0), duration(selected) - 1 / Number(manifest.fps || 24));
    $('time').value = String(currentTime);
    let displayedTime = currentTime;
    const ticket = ++requestId;
    $('frame-error').hidden = true;
    if (isStatic) {
      const frames = selected._preview_frames || [];
      const chosen = frames.reduce((best, frame) => !best || Math.abs(frame.time - currentTime) < Math.abs(best.time - currentTime) ? frame : best, null);
      if (chosen) { $('frame').src = chosen.url; displayedTime = chosen.time; currentTime = chosen.time; $('time').value = String(currentTime); }
      else { $('frame-error').textContent = 'No sampled frames are available for this shot.'; $('frame-error').hidden = false; }
    } else {
      try {
        const result = await fetch(`api/frame?shot=${encodeURIComponent(selected.id)}&t=${currentTime.toFixed(5)}`);
        if (!result.ok) { const error = await result.json(); throw new Error(error.error || 'Frame rendering failed'); }
        const image = await result.blob();
        if (ticket !== requestId) return;
        if (blobURL) URL.revokeObjectURL(blobURL);
        blobURL = URL.createObjectURL(image); $('frame').src = blobURL;
      } catch (error) {
        if (ticket !== requestId) return;
        $('frame-error').textContent = error.message; $('frame-error').hidden = false; stop();
      }
    }
    $('frame').alt = `${selected.id} ${title(selected)}, ${displayedTime.toFixed(2)} seconds, ${preview.mode || 'blocking'} review`;
    $('time-label').textContent = `${displayedTime.toFixed(2)} / ${duration(selected).toFixed(2)}s${isStatic ? ' · sample' : ''}`;
  }
  function stop() { playing = false; clearTimeout(animationTimer); $('play').textContent = isStatic ? 'Next sample' : 'Play scene'; }
  function select(shot) {
    stop(); selected = shot;
    const index = shots.indexOf(shot);
    $('shot-number').textContent = `${shot.id.replaceAll('_', ' ')} / ${shots.length} · ${locationName(shot.location)}`;
    $('shot-title').textContent = title(shot);
    $('previous').disabled = index === 0; $('next').disabled = index === shots.length - 1;
    $('time').max = String(duration(shot) - 1 / Number(manifest.fps || 24));
    const source = shot.source || {};
    $('camera').textContent = source.camera || (typeof shot.camera === 'object' ? JSON.stringify(shot.camera) : shot.camera || '');
    $('action').textContent = shot.action || shot.description || source.action || '';
    $('notice').textContent = `${preview.notice || ''} Picture review; performed voices are not included.${shot.blocking_authored === false ? ' This shot currently uses default staging.' : ''}`;
    const tracks = $('action-tracks');
    clear(tracks);
    for (const actorName of cast(shot)) {
      const actor = (shot.actors || {})[actorName] || {};
      const clips = actor.actions || (actor.action ? [actor.action] : []);
      for (const clip of clips) {
        const kind = String(clip.clip || clip.kind || 'idle');
        const begin = Number(clip.start ?? 0), finish = Number(clip.end ?? duration(shot));
        const chip = node('button', `${actorName}: ${kind} · ${begin.toFixed(2)}–${finish.toFixed(2)}s`, 'action-clip');
        chip.type = 'button';
        chip.setAttribute('aria-label', `Inspect ${actorName} ${kind} at ${begin.toFixed(2)} seconds`);
        chip.addEventListener('click', () => { stop(); displayFrame(begin); });
        tracks.append(chip);
      }
    }
    if (!tracks.children.length) tracks.append(node('p', 'No authored action clips in this shot yet.', 'muted'));
    $('props').textContent = shot.props ? `Props: ${Array.isArray(shot.props) ? shot.props.map(p => typeof p === 'string' ? p : p.id || p.name || p.type || JSON.stringify(p)).join(' · ') : JSON.stringify(shot.props)}` : '';
    clear($('shot-cast')); for (const name of cast(shot)) $('shot-cast').append(node('span', name, 'cast-chip'));
    clear($('dialogue'));
    for (const turn of shot.dialogue || []) {
      const row = node('div', undefined, 'dialogue-turn'); row.append(node('strong', turn.speaker || turn.character || ''), node('p', turn.text || '')); $('dialogue').append(row);
    }
    if (!$('dialogue').children.length) $('dialogue').append(node('p', 'No spoken dialogue in this shot.'));
    showState($('state-in'), shot.state_in || shot.opening_state, source.opening_state); showState($('state-out'), shot.state_out || shot.end_state, source.end_state);
    references(); renderLibrary(); displayFrame(0);
  }
  $('search').addEventListener('input', renderLibrary); $('cast-filter').addEventListener('change', renderLibrary); $('location-filter').addEventListener('change', renderLibrary);
  $('previous').addEventListener('click', () => select(shots[Math.max(0, shots.indexOf(selected) - 1)]));
  $('next').addEventListener('click', () => select(shots[Math.min(shots.length - 1, shots.indexOf(selected) + 1)]));
  let scrubTimer;
  $('time').addEventListener('input', () => { stop(); clearTimeout(scrubTimer); const value = Number($('time').value); scrubTimer = setTimeout(() => displayFrame(value), isStatic ? 0 : 80); });
  $('play').addEventListener('click', async () => {
    if (isStatic) { const frames = selected._preview_frames || []; const next = frames.find(f => f.time > currentTime + 0.01) || frames[0]; if (next) displayFrame(next.time); return; }
    if (playing) { stop(); return; }
    playing = true; $('play').textContent = 'Pause';
    if (currentTime >= duration(selected) - .1) currentTime = 0;
    const began = performance.now() - currentTime * 1000;
    async function tick() {
      if (!playing) return;
      const next = (performance.now() - began) / 1000;
      await displayFrame(next);
      if (next >= duration(selected) - 1 / Number(manifest.fps || 24)) stop();
      else if (playing) animationTimer = setTimeout(tick, 80);
    }
    tick();
  });
  $('frame').addEventListener('error', () => { $('frame-error').textContent = 'This preview image could not be loaded. Keep the full review folder together.'; $('frame-error').hidden = false; });
  select(selected);
})();
