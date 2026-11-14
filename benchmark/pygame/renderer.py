"""Optional SDL/Pygame-ce raster backend for a fair Episode03 shot comparison.

This backend uses the SAME original Actor.pose, cutout PNGs, foregrounds, props,
z/depth, hand binding, camera, narration and scene config as Pillow. It does NOT
replace the original engine and is not used by default.

pygame-ce is LGPL-2.1; this module is original project code, no pygame code copied.
"""
from __future__ import annotations

from functools import lru_cache
from math import isfinite
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageOps

from animation2d.episode03 import engine
from animation2d.episode03.camera_clips import sample_camera
from animation2d.episode03.kinematics import rot
from animation2d.episode03.engine import Actor, HandTransform, attachment_transform, _cues

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")


def pygame_module():
    try:
        import pygame
    except ImportError as exc:
        raise RuntimeError("This experimental backend requires pip install pygame-ce==2.5.8") from exc
    if not pygame.display.get_init():
        pygame.display.init()
        pygame.display.set_mode((1, 1))
    if not pygame.font.get_init():
        pygame.font.init()
    return pygame


@lru_cache(maxsize=128)
def _png_surface(path, mtime):
    pg = pygame_module()
    pil = engine.load_image(path)
    return pg.image.fromstring(pil.tobytes(), pil.size, "RGBA").convert_alpha()


def _surface_from_pil(pil):
    pg = pygame_module()
    return pg.image.fromstring(pil.tobytes(), pil.size, "RGBA").convert_alpha()


def _image_surface(path):
    p = Path(path)
    return _png_surface(str(p), p.stat().st_mtime_ns)


def _sprite(target, src, pivot, at, degrees, scale):
    """Affine cutout placement with pivot matching engine.kinematics.place."""
    pg = pygame_module()
    if scale <= 0 or not isfinite(scale):
        raise ValueError("Invalid Pygame sprite scale")
    origin = np.array([src.get_width()/2, src.get_height()/2], dtype=float)
    local = (origin - np.asarray(pivot, dtype=float)) * scale
    center = np.asarray(at, dtype=float) + rot(local, degrees)
    transformed = pg.transform.rotozoom(src, -degrees, scale)
    target.blit(transformed, transformed.get_rect(
        center=(int(round(center[0])), int(round(center[1])))))


@lru_cache(maxsize=128)
def _shape_image(shape, width, height, color):
    # Use the SAME tiny vector source sprite as Pillow. The *placement* and
    # compositing are rasterized by Pygame-ce, not the Pillow affine engine.
    im = Image.new("RGBA", (max(1, width), max(1, height)))
    d = ImageDraw.Draw(im)
    bbox = (1, 1, im.width-2, im.height-2)
    if shape == "ellipse":
        d.ellipse(bbox, fill=color, outline="#F4EEDC", width=3)
    else:
        d.rounded_rectangle(bbox, radius=4, fill=color, outline="#F4EEDC", width=2)
    return im


def _draw_prop(canvas, prop, transform, base):
    if prop.get("file"):
        image = _image_surface(engine._path(base, prop["file"]))
        default_pivot = [image.get_width()/2, image.get_height()/2]
    else:
        w, h = prop.get("size", [90, 50])
        image = _surface_from_pil(_shape_image(
            prop.get("shape", "rectangle"), int(w), int(h),
            prop.get("color", "#466BA3")))
        default_pivot = [w/2, h/2]
    _sprite(canvas, image, prop.get("pivot", default_pivot),
            transform.position, transform.rotation,
            float(prop.get("scale", 1)) * transform.scale)


def _font(px):
    pg = pygame_module()
    path = engine.REPO / "animation2d/project/assets/fonts/DejaVuSans.ttf"
    return pg.font.Font(str(path), px) if path.is_file() else pg.font.Font(None, px)


def _draw_blocking(canvas, actor, pose, local_time):
    """Schematic preview only: artists' part sprites are NOT available."""
    pg = pygame_module()
    color=pg.Color(engine.COLORS.get(actor.name, "#608CA5"))
    sc=float(pose["scale"])
    for bone, (a, b) in pose["bones"].items():
        if bone not in ("head", "pelvis"):
            pg.draw.line(canvas, color, tuple(a.astype(int)), tuple(b.astype(int)),
                         max(3, round((30 if bone=="torso" else 12)*sc)))
    neck=pose["neck"]
    head_a,head_b=pose["bones"]["head"]
    angle=engine.angle(head_b-head_a)
    center=neck+rot([0,-49*sc],angle)
    rx,ry=int(35*sc),int(45*sc)
    pg.draw.ellipse(canvas,"#EBDCC6",
                    (int(center[0])-rx,int(center[1])-ry,2*rx,2*ry))
    pg.draw.ellipse(canvas,color,
                    (int(center[0])-rx,int(center[1])-ry,2*rx,2*ry),max(2,round(4*sc)))
    blinking=pose["blink"] is True
    for sign in (-1,1):
        eye=center+rot([sign*12*sc,-7*sc],angle)
        if blinking:
            pg.draw.line(canvas,"#2A3033",(eye[0]-3*sc,eye[1]),
                         (eye[0]+3*sc,eye[1]),2)
        else:
            pg.draw.circle(canvas,"#2A3033",(int(eye[0]),int(eye[1])),max(2,round(2*sc)))
    font=_font(max(13,round(20*sc)))
    label=font.render(actor.name+" [BLOCKING]",True,color)
    canvas.blit(label, label.get_rect(center=(int(center[0]),int(center[1]-ry-25))))


def _draw_actor(canvas, actor, local_time, duration):
    if actor.mode == "blocking":
        return _draw_blocking(canvas, actor, actor.pose(local_time,duration),local_time)
    pg=pygame_module()
    pose=actor.pose(local_time,duration)
    blink_offset=(engine.CAST.index(actor.name) if actor.name in engine.CAST
                  else int(__import__("hashlib").sha256(actor.name.encode()).hexdigest()[:4],16)%11)
    blink=pose["blink"] if pose["blink"] is not None else (
        (local_time+blink_offset*.61)%4.1)<.12
    for part in sorted(actor.parts,key=lambda x:x.get("depth",0)):
        start,end=pose["bones"][part["bone"]]
        path=part["path"]
        if part["bone"]=="head":
            if pose["mouth"]!="X" and pose["mouth"] not in actor.face_parts:
                raise engine.AssetError("Missing authored mouth sprite")
            key=pose["mouth"]+("_blink" if blink else "")
            path=actor.face_parts.get(key,actor.face_parts.get(pose["mouth"],path))
        src=_image_surface(path)
        pivot=np.array(part["pivot"],dtype=float)
        source_end=np.array(part.get("source_end",
                          [pivot[0],pivot[1]+1]),dtype=float)
        if part.get("mirror"):
            src=pg.transform.flip(src,True,False)
            pivot[0]=src.get_width()-1-pivot[0]
            source_end[0]=src.get_width()-1-source_end[0]
        degrees=engine.angle(end-start)-engine.angle(source_end-pivot)
        factor=pose["scale"]
        if "source_end" in part:
            length=float(np.linalg.norm(source_end-pivot))
            if length <=0:
                raise engine.AssetError("Invalid part source_end")
            factor=float(np.linalg.norm(end-start))/length
        _sprite(canvas,src,pivot,start,degrees,factor)


def render_frame_pygame(manifest, shot_id, local_time, *,
                        mode="production", size=(1920,1080), audio_dir=None):
    """Re-solve the SAME source pose and render the SAME input artwork with SDL."""
    pg=pygame_module()
    data=engine.load_manifest(manifest)
    shot=next((s for s in data["shots"] if s["id"]==shot_id),None)
    if shot is None:
        raise ValueError("Unknown shot")
    duration=shot["duration"]
    if mode not in ("production","blocking") or not 0<=local_time<duration:
        raise ValueError("Invalid mode or frame time")
    canvas_size=tuple(data.get("canvas",[1920,1080]))
    base=Path(data.get("__base_dir__",engine.REPO))
    canvas=pg.Surface(canvas_size,pg.SRCALPHA,32)
    canvas.fill("#E8E1D3")
    background=shot.get("background")
    if background is None and shot.get("location"):
        folder=base/"Episode_03/assets/environments"
        background=next((str(p) for ext in (".png",".jpg")
            if (p:=folder/(shot["location"]+ext)).is_file()),None)
    if background:
        bg=engine.load_image(engine._path(base,background))
        bg=ImageOps.contain(bg,canvas_size,Image.Resampling.LANCZOS)
        surf=_surface_from_pil(bg)
        canvas.blit(surf,((canvas.get_width()-surf.get_width())//2,
                          (canvas.get_height()-surf.get_height())//2))

    configs=data.get("characters",{})
    if isinstance(configs,list):
        configs={item["id"]:item for item in configs}
    objects={p["id"]:p for p in shot.get("props",[]) if "id" in p}
    actors={name: Actor(name,configs.get(name,{}),shot.get("actors",{}).get(name,{}),
                       mode=mode,base_dir=base,cues=_cues(audio_dir,shot_id,name),
                       objects=objects) for name in shot["cast"]}
    items=[]
    for name,actor in actors.items():
        items.append((float(actor.placement.get("depth",100)),len(items),"actor",actor))
    for prop in shot.get("props",[]):
        items.append((float(prop.get("depth",110)),len(items),"prop",prop))
    for front in shot.get("foreground",[]):
        items.append((float(front.get("depth",1000)),len(items),"foreground",front))
    for _depth,_idx,kind,item in sorted(items,key=lambda x:(x[0],x[1])):
        if kind=="actor":
            _draw_actor(canvas,item,local_time,duration)
        elif kind=="foreground":
            src=_image_surface(engine._path(base,item["file"]))
            canvas.blit(src,tuple(item.get("position",[0,0])))
        else:
            transform=HandTransform(np.asarray(item.get("position",[960,600]),dtype=float),
                                    float(item.get("rotation",0)),1)
            interaction=item.get("interaction")
            if interaction:
                name=interaction["actor"]
                if name not in actors:
                    raise ValueError("Invisible attachment actor")
                if local_time>=interaction["release_at"]:
                    transform=HandTransform(np.asarray(interaction["landing"],dtype=float),
                                            float(item.get("rotation",0)),1)
                elif local_time>=interaction["attach_at"]:
                    transform=attachment_transform(actors[name],local_time,interaction,duration)
                    if not interaction.get("rotate_with_hand",False):
                        transform.rotation=float(item.get("rotation",0))
                    if not interaction.get("follow_actor_scale",False):
                        transform.scale=1
            else:
                attach=item.get("attachment")
                if attach and attach.get("start",0)<=local_time<attach.get("end",duration):
                    transform=attachment_transform(actors[attach["actor"]],local_time,attach,duration)
            _draw_prop(canvas,item,transform,base)
    camera=sample_camera(shot.get("camera",{}),
                         shot.get("camera_animation"),local_time,duration)
    zoom=float(camera.get("zoom",1))
    if not isfinite(zoom) or zoom<=0:
        raise ValueError("Invalid zoom")
    center=camera.get("center",[canvas_size[0]/2,canvas_size[1]/2])
    # Camera crop and pixel conversion are shared Pillow postprocessing in
    # the *experimental* backend. Timings state this limitation explicitly.
    picture=Image.frombytes("RGBA",canvas_size,pg.image.tostring(canvas,"RGBA"))
    crop=(center[0]-canvas_size[0]/(2*zoom),
          center[1]-canvas_size[1]/(2*zoom),
          center[0]+canvas_size[0]/(2*zoom),
          center[1]+canvas_size[1]/(2*zoom))
    picture=picture.transform(size,Image.Transform.EXTENT,crop,Image.Resampling.BICUBIC)
    if camera.get("angle",0):
        picture=picture.rotate(camera["angle"],Image.Resampling.BICUBIC,expand=False)
    if mode=="blocking":
        d=ImageDraw.Draw(picture)
        d.rectangle((0,0,size[0],32),fill="#28323B")
        d.text((12,7),"SCHEMATIC BLOCKING · "+shot_id+" · NOT FINAL CHARACTER ART",
               font=engine._font(14),fill="white")
    return picture.convert("RGB")
