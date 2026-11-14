#!/usr/bin/env python3
"""Compile all eighty screenplay shots into explicit editable animation data.

--write refreshes shots.json; --check detects stale data without rewriting it.
Default staging is blocking, not authored production motion. Original cast JPGs
remain intact; missing separated production rigs are reported by readiness().
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = Path(__file__).resolve().parent
if str(PACKAGE) not in sys.path:
    sys.path.insert(0, str(PACKAGE))
from state import CAST, initial_state, apply_events, events_for_shot, validate_state


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load_checker(root=ROOT):
    spec = importlib.util.spec_from_file_location('episode03_source_checker', root / 'Episode_03/check.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    return checker


def source_shots(root=ROOT):
    checker = load_checker(root)
    return checker.shots((root / 'Episode_03/STORY.md').read_text(encoding='utf-8'), '###', 'story')


def dialogue_cues(root, source):
    checker = load_checker(root)
    text = (root / 'Episode_03/SUBTITLES.srt').read_text(encoding='utf-8')
    checker.validate_subtitles(text, source)
    blocks = re.split(r'\n\s*\n', text.strip())
    cursor = 0
    result = []
    for shot in source:
        turns = []
        for speaker, line in shot['dialogue']:
            rows = blocks[cursor].splitlines()
            begin, end = rows[1].split(' --> ')
            turns.append({'speaker':speaker, 'text':line,
                          'start':round(checker.milliseconds(begin)/1000-shot['begin']/1000,3),
                          'end':round(checker.milliseconds(end)/1000-shot['begin']/1000,3)})
            cursor += 1
        result.append(turns)
    return result


def actor_defaults(cast, characters):
    n = len(cast)
    actors = {}
    for index, name in enumerate(cast):
        x = 960 if n == 1 else round(280 + index * 1360 / (n-1))
        actors[name] = {'position':[x,650], 'scale':characters[name]['default_scale'],
                        'depth':100+index, 'action':{'kind':'idle'}}
    return actors


def props_for_state(location, state):
    props = []
    if location in ('HOME_KITCHEN','PREP_ISLAND','STOVE_STATION'):
        props.extend([
            {'id':'blue_bowl','position':[1050,660],'depth':200,'state':state['blue_bowl']},
            {'id':'yellow_bowl','position':[1250,660],'depth':201,'state':state['yellow_bowl']},
            {'id':'empty_vase','position':[1420,660] if state['vase_location']=='island' else [1690,350],
             'depth':40 if state['vase_location']=='decoration_shelf' else 202,
             'state':{'empty':True,'location':state['vase_location']}},
        ])
    if location == 'HOME_TABLE':
        props.append({'id':'cooked_tray','position':[960,650],'depth':200,'state':{'pancakes':state['tray']}})
    return props


def apply_overrides(shots, overrides):
    require(isinstance(overrides,dict) and set(overrides)=={'version','shots'} and overrides['version']==1, 'overrides require version 1 and a shots mapping')
    require(isinstance(overrides['shots'],dict), 'override shots must be a mapping')
    indexed={shot['id']:shot for shot in shots}
    for name, changes in overrides['shots'].items():
        require(name in indexed, f'override references unknown shot {name}')
        require(isinstance(changes,dict) and set(changes)<={'camera','actors','props','foreground'}, f'{name}: unknown override field; narrative and state are immutable')
        shot=indexed[name]
        if 'camera' in changes:
            require(isinstance(changes['camera'],dict) and set(changes['camera'])<={'zoom','center'}, f'{name}: unknown camera override field')
            shot['camera'].update(deepcopy(changes['camera']))
        if 'actors' in changes:
            require(isinstance(changes['actors'],dict) and set(changes['actors'])<=set(shot['cast']), f'{name}: override actor must be visible')
            for actor, values in changes['actors'].items():
                require(isinstance(values,dict) and set(values)<={'position','scale','depth','action'}, f'{name}: unknown actor override field')
                target=shot['actors'][actor]
                for key,value in values.items():
                    if key=='action':
                        require(isinstance(value,dict),f'{name}: actor action override must be a mapping')
                        target['action'].update(deepcopy(value))
                    else:
                        target[key]=deepcopy(value)
        for field in ('props','foreground'):
            if field in changes:
                require(isinstance(changes[field],list),f'{name}: {field} override must be a list')
                shot[field]=deepcopy(changes[field])
        if changes:
            shot['blocking_authored']=True
    return shots


def compile_manifest(root=ROOT, overrides_path=None):
    root = Path(root)
    source = source_shots(root)
    titles=dict(re.findall(r'^### (SHOT_\d{3}) \| [^|]+ \| (.+)$',(root/'Episode_03/STORY.md').read_text(encoding='utf-8'),re.M))
    require(len(titles)==80,'all eighty source shots need a beat title')
    character_file = root / 'animation2d/episode03/characters.json'
    char_data = json.loads(character_file.read_text(encoding='utf-8'))
    require(char_data['version'] == 1, 'unsupported character schema version')
    characters = char_data['characters']
    override_file=Path(overrides_path) if overrides_path is not None else root/'animation2d/episode03/overrides.json'
    overrides=json.loads(override_file.read_text(encoding='utf-8'))
    cues = dialogue_cues(root, source)
    source_files = ['Episode_03/STORY.md','Episode_03/CONTINUITY.md','Episode_03/SUBTITLES.srt',
                    'animation2d/episode03/characters.json']
    manifest = {'version':1,'compiler_version':1,'fps':24,'canvas':[1920,1080], 'duration':1200,
                'source_sha256':{name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in source_files},
                'status':'blocking data; production rigs, authored motion and performed voices still require review',
                'dialogue_timing':'provisional screenplay SRT estimates; replace with accepted performance timings',
                'characters':characters,'shots':[]}
    manifest['source_sha256']['animation2d/episode03/overrides.json']=hashlib.sha256(override_file.read_bytes()).hexdigest()
    state = initial_state()
    for index, source_shot in enumerate(source):
        fields = source_shot['fields']
        number = index+1
        cast = [name.strip() for name in fields['Visible cast'].split(',')]
        before = deepcopy(state)
        events = events_for_shot(number)
        state = apply_events(state, events)
        location = fields['Location']
        extension = '.jpg' if location in ('HOME_KITCHEN','HOME_TABLE') else '.png'
        shot = {'id':f'SHOT_{number:03}', 'title':titles[f'SHOT_{number:03}'], 'start':index*15,'duration':15,'cast':cast,
                'location':location,'background':f'Episode_03/assets/environments/{location}{extension}',
                'camera':{'zoom':1,'center':[960,540]}, 'actors':actor_defaults(cast,characters),
                'props':props_for_state(location,before),'dialogue':cues[index],
                'events':events, 'state_in':before,'state_out':deepcopy(state),
                'source':{'camera':fields['Camera'],'action':fields['Action'],
                          'opening_state':fields['Opening state'],'end_state':fields['End state'],
                          'continuity':fields['Continuity'],'picture':fields['Picture']},
                'blocking_authored':False,'production_ready':False}
        manifest['shots'].append(shot)
    apply_overrides(manifest['shots'],overrides)
    validate_manifest(manifest, root=root, check_source=True)
    return manifest


def validate_manifest(manifest, root=ROOT, check_source=True):
    require(manifest.get('version')==1 and manifest.get('fps')==24 and manifest.get('duration')==1200, 'episode must be 1200 seconds at 24fps, schema version 1')
    characters = manifest['characters']
    require(set(characters)==set(CAST), 'exactly the six established characters are required')
    presets = [actor['voice']['preset'] for actor in characters.values()]
    require(len(set(presets))==6, 'all six characters need distinct voice presets')
    require(all(actor['voice']['engine']=='kokoro' and .5<=actor['voice']['speed']<=1.3 for actor in characters.values()), 'invalid Kokoro voice settings')
    source = source_shots(Path(root)) if check_source else None
    require(len(manifest['shots'])==80, 'exactly eighty shots required')
    state = initial_state()
    for index, shot in enumerate(manifest['shots']):
        require(shot['id']==f'SHOT_{index+1:03}' and shot['start']==index*15 and shot['duration']==15, 'shots need ordered continuous fifteen-second timing')
        require(set(shot['cast'])<=set(CAST) and len(shot['cast'])==len(set(shot['cast'])), f"{shot['id']}: unknown or duplicate actor")
        require(set(shot['actors'])==set(shot['cast']), f"{shot['id']}: actors must match the visible cast")
        require(shot['camera']['zoom']>0 and len(shot['camera']['center'])==2, f"{shot['id']}: invalid camera blocking")
        require(len({prop['id'] for prop in shot['props']})==len(shot['props']), f"{shot['id']}: duplicate prop inventory")
        previous_end = 0
        for turn in shot['dialogue']:
            require(turn['speaker'] in shot['cast'], f"{shot['id']}: dialogue speaker is not visible")
            require(0<=turn['start']<turn['end']<=15 and turn['start']>=previous_end, f"{shot['id']}: dialogue timing exceeds shot or overlaps")
            previous_end=turn['end']
        for actor in shot['actors'].values():
            require(actor['scale']>0 and len(actor['position'])==2 and actor['action']['kind'] in ('idle','reach','walk','gesture'), f"{shot['id']}: invalid actor blocking")
        for prop in shot['props']:
            if 'attachment' in prop:
                link=prop['attachment']
                require(link['actor'] in shot['cast'] and link['hand'] in ('left','right') and 0<=link['start']<link['end']<=15, f"{shot['id']}: invalid prop attachment")
        validate_state(shot['state_in']);validate_state(shot['state_out'])
        require(shot['state_in']==state, f"{shot['id']}: continuity does not match previous shot")
        require(shot['events']==events_for_shot(index+1), f"{shot['id']}: events differ from explicit screenplay ledger")
        state=apply_events(state,shot['events'])
        require(shot['state_out']==state, f"{shot['id']}: end state differs from applied events")
        if source is not None:
            expected=source[index]
            require([(turn['speaker'],turn['text']) for turn in shot['dialogue']]==expected['dialogue'], f"{shot['id']}: dialogue differs from screenplay")
            require(shot['cast']==[name.strip() for name in expected['fields']['Visible cast'].split(',')], f"{shot['id']}: cast differs from screenplay")
            require(shot['location']==expected['fields']['Location'], f"{shot['id']}: location differs from screenplay")
            for key,source_key in (('camera','Camera'),('action','Action'),('opening_state','Opening state'),('end_state','End state'),('continuity','Continuity'),('picture','Picture')):
                require(shot['source'][key]==expected['fields'][source_key], f"{shot['id']}: preserved source {key} differs")
    require(state['meal_finished'] and state['eaten_total']==12 and state['stove']=='OFF' and state['vase_location']=='decoration_shelf', 'final story state incomplete')
    return manifest


def readiness(manifest, root=ROOT):
    missing = []
    for name, actor in manifest['characters'].items():
        if not (Path(root)/actor['rig']).is_file():
            missing.append(f'{name}: missing separated production rig {actor["rig"]}')
        for path in actor['reference'].values():
            if not (Path(root)/path).is_file():
                missing.append(f'{name}: missing reference {path}')
    return {'ready':not missing,'missing':missing,'status':'asset existence only; visual identity and performed motion still need review'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check',action='store_true')
    mode.add_argument('--write',action='store_true')
    args=parser.parse_args()
    expected=compile_manifest()
    path=PACKAGE/'shots.json'
    encoded=json.dumps(expected,indent=2,ensure_ascii=False)+'\n'
    if args.write:
        path.write_text(encoded,encoding='utf-8')
        print('Wrote eighty shots, 240 screenplay dialogue turns and continuous state ledger:',path)
    else:
        require(path.is_file() and path.read_text(encoding='utf-8')==encoded,'shots.json is stale; run python animation2d/episode03/manifest.py --write')
        print('PASS: eighty shots, 240 exact screenplay dialogue turns, six distinct voices and continuity ledger match source')
    report=readiness(expected)
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError,KeyError) as error:
        print(f'FAIL: {error}',file=sys.stderr)
        sys.exit(1)
