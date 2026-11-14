"""Independent six-actor cutout engine; production and schematic modes are explicit.

Rig PNGs use local pelvis-origin coordinates and an ordered part list. Existing
JPG character sheets are references only and are never cut up by this module.
"""
from dataclasses import dataclass
from functools import lru_cache
import json
import math
import hashlib
import re
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .kinematics import angle, camera_point, ease, ik, place, rot, walk_foot, wrist_angle
from .actions import ActionMixer
from .camera_clips import sample_camera

REPO = Path(__file__).resolve().parents[2]
CAST = ('DAN','MAYA','NINA','LEO','ELLA','MAX')
COLORS = dict(DAN='#4D9BD0', MAYA='#783554', NINA='#167E83', LEO='#D87429', ELLA='#DE756D', MAX='#5B9046')
DEFAULT_ANCHORS = dict(neck=[0,-195], shoulder_left=[-48,-165], shoulder_right=[48,-165], hip_left=[-30,30], hip_right=[30,30])
DEFAULT_LENGTHS = dict(upper_arm=135, forearm=125, thigh=180, shin=170)
REQUIRED_BONES = {'head','torso','pelvis'} | {f'{bone}.{side}' for bone in ('upper_arm','forearm','hand','thigh','shin','foot') for side in ('left','right')}


class AssetError(ValueError):
    """A required production-art or mouth-cue asset is missing or invalid."""


@dataclass
class HandTransform:
    position: np.ndarray
    rotation: float
    scale: float


@lru_cache(maxsize=128)
def _image(path, mtime):
    with Image.open(path) as image:
        return image.convert('RGBA')


def load_image(path):
    path = Path(path)
    return _image(str(path), path.stat().st_mtime_ns).copy()


def _font(size=22):
    font = REPO/'animation2d/project/assets/fonts/DejaVuSans.ttf'
    return ImageFont.truetype(str(font), size) if font.exists() else ImageFont.load_default()


def load_manifest(manifest):
    if isinstance(manifest, (str, Path)):
        path=Path(manifest).resolve()
        data=json.loads(path.read_text())
        # Repository-relative assets are the shared data contract.
        data.setdefault('__base_dir__', str(REPO))
        return data
    return manifest


def _path(base, value):
    path=Path(value)
    return path if path.is_absolute() else Path(base)/path


class Actor:
    """One actor owns its configuration, artwork, pose state and speech cues."""
    def __init__(self, name, config=None, placement=None, *, mode='blocking', base_dir=REPO, cues=None, objects=None):
        if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,31}',name):
            raise ValueError(f'Invalid character ID: {name}')
        if mode not in ('blocking','production'):
            raise ValueError('mode must be blocking or production')
        self.name=name
        self.config=dict(config or {})
        self.placement=dict(placement or {})
        self.objects=dict(objects or {})
        self.mode=mode
        self.cues=list(cues or [])
        self.rig={}
        self.parts=[]
        if mode=='production':
            self._load_rig(base_dir)
        self.anchors={**DEFAULT_ANCHORS, **self.rig.get('anchors',{})}
        self.lengths={**DEFAULT_LENGTHS, **self.rig.get('lengths',{})}
        for length in self.lengths.values():
            if not isinstance(length,(int,float)) or not math.isfinite(length) or length<=0:
                raise AssetError(f'{name}: invalid rig bone length')
        previous=0.0
        for cue in self.cues:
            try:
                valid=(isinstance(cue,dict) and isinstance(cue.get('value'),str)
                       and len(cue['value'])==1 and cue['value'] in 'ABCDEFGHX'
                       and math.isfinite(cue['start']) and math.isfinite(cue['end'])
                       and 0<=cue['start']<cue['end'] and cue['start']>=previous)
            except (KeyError,TypeError):
                valid=False
            if not valid:
                raise AssetError(f'{name}: invalid or overlapping mouth cues')
            previous=cue['end']
        if mode=='production':
            required={cue['value'] for cue in self.cues}-{'X'}
            missing=required-self.face_parts.keys()
            if missing:
                raise AssetError(f'{name}: missing authored mouth sprites {sorted(missing)}')

    def _load_rig(self, base):
        if not self.config.get('rig'):
            raise AssetError(f'{self.name}: production requires a transparent PNG part rig; none configured')
        path=_path(base,self.config['rig'])
        if not path.is_file():
            raise AssetError(f'{self.name}: missing production rig {path}; use blocking mode for schematics')
        self.rig=json.loads(path.read_text())
        if self.rig.get('version')!=1:
            raise AssetError(f'{self.name}: unsupported rig version')
        seen=set()
        for part in self.rig.get('parts',[]):
            bone=part.get('bone')
            if bone not in REQUIRED_BONES:
                raise AssetError(f'{self.name}: unsupported part bone {bone}')
            sprite=(path.parent/part['file']).resolve()
            if not sprite.is_relative_to(path.parent.resolve()) or sprite.suffix.lower()!='.png':
                raise AssetError(f'{self.name}: part must be a PNG inside the rig folder')
            if not sprite.is_file():
                raise AssetError(f'{self.name}: missing part {sprite.name}')
            with Image.open(sprite) as artwork:
                if artwork.format!='PNG' or 'A' not in artwork.getbands() or artwork.getchannel('A').getextrema()[0]>=255 or artwork.getchannel('A').getextrema()[1]==0:
                    raise AssetError(f'{self.name}: {sprite.name} needs nonempty transparent PNG artwork')
            if len(part.get('pivot',[]))!=2:
                raise AssetError(f'{self.name}: part needs a two-coordinate pivot')
            self.parts.append({**part,'path':sprite})
            seen.add(bone)
        missing=REQUIRED_BONES-seen
        if missing:
            raise AssetError(f'{self.name}: incomplete production rig, missing {sorted(missing)}')
        # Optional authored face sprites (cue + blink combinations) retain skin/identity.
        self.face_parts={}
        for key, filename in self.rig.get('faces',{}).items():
            sprite=(path.parent/filename).resolve()
            if not sprite.is_relative_to(path.parent.resolve()) or sprite.suffix.lower()!='.png' or not sprite.is_file():
                raise AssetError(f'{self.name}: invalid face sprite {key}')
            with Image.open(sprite) as artwork:
                if artwork.format!='PNG' or 'A' not in artwork.getbands() or artwork.getchannel('A').getextrema()[0]>=255 or artwork.getchannel('A').getextrema()[1]==0:
                    raise AssetError(f'{self.name}: face sprite {key} needs nonempty transparent PNG artwork')
            self.face_parts[key]=sprite

    def mouth_shape(self,t):
        return next((cue['value'] for cue in self.cues if cue['start']<=t<cue['end']), 'X')

    def pose(self,t,duration=15):
        """Evaluate reusable layered clips, then solve the original per-part IK rig."""
        placement=self.placement
        motion=ActionMixer(placement,duration,objects=self.objects).sample(t)
        root=motion.root
        scale=float(placement.get('scale',1))
        if scale<=0 or not math.isfinite(scale):
            raise ValueError('actor scale must be finite and positive')
        lean=motion.lean
        def point(value):return root+rot(np.array(value)*scale,lean)
        neck=point(self.anchors['neck'])
        bones={'pelvis':(root,root+rot([0,40*scale],lean)),
               'torso':(neck,root),
               'head':(neck,neck+rot([0,100*scale],lean+motion.head_turn))}
        hands={}; joints={'root':root,'neck':neck}
        for side,sign in [('left',-1),('right',1)]:
            shoulder=point(self.anchors['shoulder_'+side])
            upper=self.lengths['upper_arm']*scale
            lower=self.lengths['forearm']*scale
            rest=shoulder+rot([sign*15*scale,(upper+lower)*.91],lean)
            target=rest.copy()
            channel=motion.hand_targets.get(side)
            if channel is not None:
                dest, weight, clip, progress=channel
                if dest is None:
                    dest=shoulder+np.array([sign*80*scale,-60*scale])
                target=rest+(dest-rest)*weight
                if clip in ('gesture','stir','pour','eat'):
                    frequency={'gesture':3,'stir':9,'pour':2,'eat':2}[clip]
                    amplitude={'gesture':10,'stir':12,'pour':6,'eat':8}[clip]
                    target+=np.array([amplitude*scale*math.sin(t*frequency),
                                      amplitude*scale*math.cos(t*frequency)])*weight
            elif motion.walking:
                target=shoulder+rot([0,(upper+lower)*.91],sign*(36 if motion.running else 22)*math.sin(root[0]*.03))
            elbow,wrist=ik(shoulder,target,upper,lower,sign)
            wrist_spec=placement.get('action',{})
            if 'actions' in placement:
                wrist_spec=next((a for a in reversed(placement['actions']) if a.get('wrist_rotation') is not None),{})
            hand_rotation=wrist_angle(angle(wrist-elbow),wrist_spec.get('wrist_rotation'))
            hand_end=wrist+rot([0,30*scale],hand_rotation)
            hands[side]=HandTransform(wrist,hand_rotation,scale)
            bones['upper_arm.'+side]=(shoulder,elbow)
            bones['forearm.'+side]=(elbow,wrist)
            bones['hand.'+side]=(wrist,hand_end)
            hip=point(self.anchors['hip_'+side])
            ground=root[1]+(self.anchors['hip_'+side][1]+self.lengths['thigh']+self.lengths['shin'])*scale
            # A planted world-space target is only useful if both leg bones
            # can actually reach it. The old straight-leg ground height
            # exhausted IK reach and made solved ankles slide despite a
            # mathematically planted walk_foot() target. Reserve some knee
            # flexion in modern, data-driven scenes. Legacy shots stay intact.
            foot_lock=placement.get('foot_lock', 'actions' in placement)
            if type(foot_lock) is not bool:
                raise ValueError('foot_lock must be boolean')
            stride=(160 if motion.running else 96)
            if foot_lock:
                stride*=scale/.6  # gait adapts to rig scale rather than cast name
                ground-=max(32*scale, (160*scale/.6)*.18)
            ankle=np.array([hip[0]+sign*10*scale,ground])
            if motion.walking:
                ankle=walk_foot(root,self.anchors['hip_'+side][0],scale,side,ground,stride)
            if motion.sitting:
                seated=np.array([hip[0]+sign*165*scale,hip[1]+165*scale])
                ankle=ankle*(1-motion.sitting)+seated*motion.sitting
            knee,ankle=ik(hip,ankle,self.lengths['thigh']*scale,self.lengths['shin']*scale,-sign)
            bones['thigh.'+side]=(hip,knee)
            bones['shin.'+side]=(knee,ankle)
            bones['foot.'+side]=(ankle,ankle+np.array([sign*35*scale,0]))
            joints.update({f'shoulder_{side}':shoulder,f'elbow_{side}':elbow,
                           f'wrist_{side}':wrist,f'hip_{side}':hip,
                           f'knee_{side}':knee,f'ankle_{side}':ankle})
        return dict(root=root,neck=neck,bones=bones,hands=hands,joints=joints,
                    scale=scale,lean=lean,mouth=self.mouth_shape(t),
                    emotion=motion.emotion,blink=motion.blink,look=motion.look,
                    active_actions=motion.active)

    def solved_hand(self,t,hand='right',duration=15):
        if hand not in ('left','right'):
            raise ValueError('hand must be left or right')
        return self.pose(t,duration)['hands'][hand]

    def draw(self,canvas,t,duration=15):
        pose=self.pose(t,duration)
        if self.mode=='blocking':
            self._draw_blocking(canvas,pose,t)
            return
        blink_offset=(CAST.index(self.name) if self.name in CAST else int(hashlib.sha256(self.name.encode()).hexdigest()[:4],16)%11)
        blink=pose['blink'] if pose['blink'] is not None else ((t+blink_offset*.61)%4.1)<.12
        for part in sorted(self.parts,key=lambda item:item.get('depth',0)):
            start,end=pose['bones'][part['bone']]
            sprite_path=part['path']
            if part['bone']=='head':
                if pose['mouth']!='X' and pose['mouth'] not in self.face_parts:
                    raise AssetError(f'{self.name}: missing authored mouth sprite {pose["mouth"]}')
                key=pose['mouth']+('_blink' if blink else '')
                sprite_path=self.face_parts.get(key,self.face_parts.get(pose['mouth'],sprite_path))
            sprite=load_image(sprite_path)
            pivot=np.array(part['pivot'],dtype=float)
            source_end=np.array(part.get('source_end',pivot+[0,1]),dtype=float)
            if part.get('mirror'):
                sprite=ImageOps.mirror(sprite)
                pivot[0]=sprite.width-1-pivot[0]
                source_end[0]=sprite.width-1-source_end[0]
            degrees=angle(end-start)-angle(source_end-pivot)
            factor=pose['scale']
            if 'source_end' in part:
                length=float(np.linalg.norm(source_end-pivot))
                if length<=0:raise AssetError('part source_end must differ from pivot')
                factor=float(np.linalg.norm(end-start))/length
            place(canvas,sprite,pivot,start,degrees,factor)

    def _draw_blocking(self,canvas,pose,t):
        d=ImageDraw.Draw(canvas)
        color=COLORS.get(self.name,'#608CA5'); scale=pose['scale']
        for bone,(a,b) in pose['bones'].items():
            if bone not in ('head','pelvis'):
                width=max(3,round((30 if bone=='torso' else 12)*scale))
                d.line([tuple(a),tuple(b)],fill=color,width=width)
        neck=pose['neck']
        head_a,head_b=pose['bones']['head']
        head_angle=angle(head_b-head_a)
        center=neck+rot([0,-49*scale],head_angle)
        rx,ry=35*scale,45*scale
        d.ellipse((center[0]-rx,center[1]-ry,center[0]+rx,center[1]+ry),fill='#EBDCC6',outline=color,width=max(2,round(4*scale)))
        offset=(CAST.index(self.name) if self.name in CAST else int(hashlib.sha256(self.name.encode()).hexdigest()[:4],16)%11)
        blinking=pose['blink'] if pose['blink'] is not None else ((t+offset*.61)%4.1)<.12
        gaze=np.zeros(2)
        if pose['look'] is not None:
            toward=np.asarray(pose['look'],dtype=float)-center
            gaze=np.clip(toward/max(10,100*scale),-1,1)*2*scale
        for sign in (-1,1):
            eye=center+rot([sign*12*scale,-7*scale],head_angle)
            if blinking:
                d.line((eye[0]-4*scale,eye[1],eye[0]+4*scale,eye[1]),fill='#2A3033',width=max(1,round(2*scale)))
            else:
                eye=eye+gaze
                d.ellipse((eye[0]-2,eye[1]-2,eye[0]+2,eye[1]+2),fill='#2A3033')
        y=center[1]+17*scale
        if pose['mouth']=='X' and pose.get('emotion') in ('happy','excited'):
            d.arc((center[0]-10*scale,y-10*scale,center[0]+10*scale,y+7*scale),0,180,fill='#643E39',width=2)
        elif pose['mouth']=='X':d.line((center[0]-8*scale,y,center[0]+8*scale,y),fill='#643E39',width=2)
        else:d.ellipse((center[0]-8*scale,y-3*scale,center[0]+8*scale,y+7*scale),fill='#643E39')
        label=self.name+' [BLOCKING]'
        d.text((center[0],center[1]-ry-25),label,font=_font(max(14,round(20*scale))),anchor='mm',fill=color,stroke_width=2,stroke_fill='white')


def attachment_transform(actor,t,attachment,duration=15):
    """A prop offset rotates and scales with the solved wrist, including clamp."""
    hand=actor.solved_hand(t,attachment.get('hand','right'),duration)
    offset=rot(np.asarray(attachment.get('offset',[0,0]),dtype=float)*hand.scale,hand.rotation)
    return HandTransform(hand.position+offset, hand.rotation+float(attachment.get('rotation',0)), hand.scale)


def _cues(audio_dir,shot_id,name):
    if audio_dir is None:return []
    file=Path(audio_dir)/shot_id/(name+'.cues.json')
    if not file.exists():return []
    data=json.loads(file.read_text())
    return data.get('mouthCues',[]) if isinstance(data,dict) else data


def _draw_prop(canvas,prop,transform,base):
    if prop.get('file'):
        pic=load_image(_path(base,prop['file']))
        place(canvas,pic,prop.get('pivot',[pic.width/2,pic.height/2]),transform.position,transform.rotation,
              float(prop.get('scale',1))*transform.scale)
        return
    # Editable vector props are allowed in both modes; no cast likeness is implied.
    w,h=prop.get('size',[90,50]);color=prop.get('color','#466BA3')
    pic=Image.new('RGBA',(max(1,int(w)),max(1,int(h))))
    d=ImageDraw.Draw(pic)
    box=(1,1,pic.width-2,pic.height-2)
    if prop.get('shape','rectangle')=='ellipse':d.ellipse(box,fill=color,outline='#F4EEDC',width=3)
    else:d.rounded_rectangle(box,radius=4,fill=color,outline='#F4EEDC',width=2)
    place(canvas,pic,prop.get('pivot',[w/2,h/2]),transform.position,transform.rotation,float(prop.get('scale',1))*transform.scale)


def render_frame(manifest,shot_id,local_time,mode='blocking',size=(960,540),audio_dir=None):
    data=load_manifest(manifest)
    shots=data['shots']
    shot=next((s for s in shots if s['id']==shot_id),None)
    if shot is None:raise ValueError(f'Unknown shot: {shot_id}')
    duration=float(shot['duration'])
    if not math.isfinite(local_time) or not 0<=local_time<duration:
        raise ValueError(f'local_time must be within [0,{duration})')
    if mode not in ('blocking','production'):raise ValueError('mode must be blocking or production')
    canvas_size=tuple(data.get('canvas',[1920,1080]))
    if len(size)!=2 or min(size)<=0:raise ValueError('size must contain two positive dimensions')
    base=Path(data.get('__base_dir__',REPO))
    canvas=Image.new('RGBA',canvas_size,'#E8E1D3')
    background=shot.get('background')
    if background is None and shot.get('location'):
        folder=base/'Episode_03/assets/environments'
        candidates=[folder/(shot['location']+ext) for ext in ('.png','.jpg')]
        background=next((str(p) for p in candidates if p.is_file()),None)
    if background:
        bg=load_image(_path(base,background))
        bg=ImageOps.contain(bg,canvas_size,Image.Resampling.LANCZOS)
        canvas.alpha_composite(bg,((canvas.width-bg.width)//2,(canvas.height-bg.height)//2))
    configs=data.get('characters',{})
    if isinstance(configs,list):configs={item['id']:item for item in configs}
    objects={prop['id']:prop for prop in shot.get('props',[]) if 'id' in prop}
    actors={name:Actor(name,configs.get(name,{}),shot.get('actors',{}).get(name,{}),mode=mode,base_dir=base,
                       cues=_cues(audio_dir,shot_id,name),objects=objects) for name in shot['cast']}
    items=[]
    for name,actor in actors.items():
        items.append((float(actor.placement.get('depth',100)),len(items),'actor',actor))
    for prop in shot.get('props',[]):items.append((float(prop.get('depth',110)),len(items),'prop',prop))
    for foreground in shot.get('foreground',[]):items.append((float(foreground.get('depth',1000)),len(items),'foreground',foreground))
    for _,_,kind,item in sorted(items,key=lambda item:(item[0],item[1])):
        if kind=='actor':item.draw(canvas,local_time,duration)
        elif kind=='foreground':
            fg=load_image(_path(base,item['file']))
            canvas.alpha_composite(fg,tuple(item.get('position',[0,0])))
        else:
            transform=HandTransform(np.array(item.get('position',[960,600]),dtype=float),float(item.get('rotation',0)),1)
            interaction=item.get('interaction')
            if interaction:
                # Modern data-driven prop lifetime: one object, wrist-following
                # while held, final grounded position after release.  This is
                # shared by all characters and never replaces the legacy API.
                name=interaction['actor']
                if name not in actors:
                    raise ValueError(f'Interaction references invisible actor {name}')
                if local_time >= interaction['release_at']:
                    transform=HandTransform(np.asarray(interaction['landing'],dtype=float),
                                            float(item.get('rotation',0)),1)
                elif local_time >= interaction['attach_at']:
                    transform=attachment_transform(actors[name],local_time,interaction,duration)
                    if not interaction.get('rotate_with_hand',False):
                        transform.rotation=float(item.get('rotation',0))
                    if not interaction.get('follow_actor_scale',False):
                        transform.scale=1  # props retain size when gripped/released
            else:
                attachment=item.get('attachment')
                if attachment and attachment.get('start',0)<=local_time<attachment.get('end',duration):
                    name=attachment['actor']
                    if name not in actors:raise ValueError(f'Attachment references invisible actor {name}')
                    transform=attachment_transform(actors[name],local_time,attachment,duration)
            _draw_prop(canvas,item,transform,base)
    camera=sample_camera(shot.get('camera',{}), shot.get('camera_animation'), local_time, duration)
    zoom=float(camera.get('zoom',1))
    camera_point([0,0],camera,size,canvas_size)  # Validate the same transform used by tests/UI.
    center=camera.get('center',[canvas.width/2,canvas.height/2])
    box=(center[0]-canvas.width/(2*zoom),center[1]-canvas.height/(2*zoom),
         center[0]+canvas.width/(2*zoom),center[1]+canvas.height/(2*zoom))
    canvas=canvas.transform(tuple(map(int,size)),Image.Transform.EXTENT,box,Image.Resampling.BICUBIC)
    if camera.get('angle',0):
        camera_angle=float(camera['angle'])
        if not math.isfinite(camera_angle) or abs(camera_angle)>45:
            raise ValueError('Camera angle must be finite and within 45 degrees')
        canvas=canvas.rotate(camera_angle,Image.Resampling.BICUBIC,expand=False)
    if mode=='blocking':
        d=ImageDraw.Draw(canvas)
        d.rectangle((0,0,size[0],32),fill='#28323B')
        d.text((12,7),'SCHEMATIC BLOCKING · '+shot_id+' · NOT FINAL CHARACTER ART',font=_font(14),fill='white')
    return canvas.convert('RGB')


def production_readiness(manifest,shot_id,audio_dir=None):
    """Return asset errors for all visible actors without rendering or hiding gaps."""
    data=load_manifest(manifest)
    shot=next((item for item in data['shots'] if item['id']==shot_id),None)
    if shot is None:raise ValueError(f'Unknown shot: {shot_id}')
    configs=data.get('characters',{})
    if isinstance(configs,list):configs={item['id']:item for item in configs}
    errors=[]
    objects={prop['id']:prop for prop in shot.get('props',[]) if 'id' in prop}
    for name in shot['cast']:
        try:
            Actor(name,configs.get(name,{}),shot.get('actors',{}).get(name,{}),mode='production',
                  base_dir=data.get('__base_dir__',REPO),cues=_cues(audio_dir,shot_id,name),objects=objects)
        except (AssetError,OSError,ValueError,KeyError,TypeError) as exc:
            errors.append(f'{name}: {exc}')
    return errors
