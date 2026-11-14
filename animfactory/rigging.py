"""Browser-safe 15-part PNG character import, visual rig geometry and immutable edits.

The CANONICAL rig is the existing 15-part cutout-v1 schema; no second IK model,
AI provider, segmentation tool, or new art format is introduced. Source PNGs and
the original rig.json are immutable. Edits produce content-addressed JSON rig
versions and switch only the registered asset pointer (undo can restore it).
"""
from __future__ import annotations

import base64
from copy import deepcopy
from io import BytesIO
import json
import math
from pathlib import Path
import re
import tempfile

from PIL import Image, UnidentifiedImageError

from .project import BONES, Project, _contained, _read_rig, hash_file
from .schema import valid_id, validate_project, point, number

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 48 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_777_216
PARTS = tuple(sorted(BONES))
ANCHORS = ("neck", "shoulder_left", "shoulder_right",
           "hip_left", "hip_right")
LENGTHS = ("upper_arm", "forearm", "thigh", "shin")
DEFAULT_ANCHORS = {
    "neck": [0,-195], "shoulder_left": [-48,-165],
    "shoulder_right": [48,-165], "hip_left": [-30,30],
    "hip_right": [30,30],
}
DEFAULT_LENGTHS = {"upper_arm": 135, "forearm": 125, "thigh": 180, "shin": 170}
DEPTHS = {
    "thigh.left": 3, "shin.left": 4, "foot.left": 5,
    "thigh.right": 6, "shin.right": 7, "foot.right": 8,
    "upper_arm.left": 10, "forearm.left": 11, "hand.left": 12,
    "pelvis": 20, "torso": 25, "head": 30,
    "upper_arm.right": 32, "forearm.right": 33, "hand.right": 34,
}
HEX = re.compile(r"^[0-9a-f]{64}$")


def _sprite(data: bytes, bone: str):
    """Decode once and ensure the layer REALLY has nonempty transparent pixels."""
    if not isinstance(data, bytes) or not 50 <= len(data) <= MAX_IMAGE_BYTES:
        raise ValueError(f"{bone}: PNG exceeds layer-size bounds")
    try:
        with Image.open(BytesIO(data)) as im:
            if im.format != "PNG" or "A" not in im.getbands():
                raise ValueError(f"{bone}: requires PNG with alpha channel")
            if im.width * im.height > MAX_IMAGE_PIXELS or not 1 <= im.width <= 8192 or not 1 <= im.height <= 8192:
                raise ValueError(f"{bone}: PNG pixel dimensions exceed safe bounds")
            lo, hi = im.getchannel("A").getextrema()
            if lo >= 255 or hi == 0:
                raise ValueError(f"{bone}: must contain both transparent and visible pixels")
            im.load()
            return im.size
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError(f"{bone}: corrupt or unsafe PNG") from exc


def decode_layers(payload):
    """JSON base64, 15 exact semantic bone roles; reject unknown paths and duplicates."""
    if not isinstance(payload, dict) or set(payload) != set(PARTS):
        missing = sorted(set(PARTS)-set(payload)) if isinstance(payload,dict) else list(PARTS)
        extra = sorted(set(payload)-set(PARTS)) if isinstance(payload,dict) else []
        raise ValueError(f"Expected exactly 15 semantic PNG layers; missing={missing} extra={extra}")
    raw = {}
    total = 0
    for bone in PARTS:
        encoded = payload[bone]
        if not isinstance(encoded, str) or len(encoded) > (MAX_IMAGE_BYTES * 4 // 3 + 8):
            raise ValueError(f"{bone}: invalid base64 payload")
        try:
            raw[bone] = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError(f"{bone}: invalid base64 image") from exc
        total += len(raw[bone])
        if total > MAX_TOTAL_BYTES:
            raise ValueError("Combined PNG layers exceed import limit")
        _sprite(raw[bone], bone)
    return raw


def import_layers(project: Project, character_id, layers, *, source="browser-user-import",
                  license="unspecified"):
    """Atomic 15-part import using existing Project.import_rig and checksums."""
    valid_id(character_id, "character")
    if not isinstance(layers, dict) or set(layers) != set(PARTS):
        raise ValueError("A complete set of 15 named body-part PNGs is required")
    sizes = {}
    for bone, data in layers.items():
        sizes[bone] = _sprite(data, bone)
    with tempfile.TemporaryDirectory(prefix="animfactory-rig-") as temp:
        folder = Path(temp)
        parts = []
        for bone in PARTS:
            w, h = sizes[bone]
            filename = bone.replace(".", "_") + ".png"
            (folder / filename).write_bytes(layers[bone])
            pivot = [round(w/2, 2), round(h*.12, 2)]
            end = [round(w/2, 2), round(h*.88, 2)]
            if math.dist(pivot, end) <= 1:
                raise ValueError(f"{bone}: sprite too short to define a bone; edit artwork first")
            parts.append({
                "id": bone.replace(".", "_"), "bone": bone, "file": filename,
                "pivot": pivot, "source_end": end, "depth": DEPTHS[bone],
            })
        doc = {"version": 1, "anchors": deepcopy(DEFAULT_ANCHORS),
               "lengths": deepcopy(DEFAULT_LENGTHS),
               "parts": parts, "faces": {}}
        file = folder / "rig.json"
        file.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        return project.import_rig(file, character_id, source_label=source,
                                  license_label=license)


def _active(project, character):
    valid_id(character, "character ID")
    actor = project.doc["characters"].get(character)
    if not actor:
        raise KeyError("Unknown project character")
    aid = actor["rig_asset"]
    asset = project.doc["assets"][aid]
    if asset["kind"] != "rig":
        raise ValueError("Character does not reference a rig asset")
    file = _contained(project.root, asset["path"])
    if not file.is_file() or hash_file(file) != asset["sha256"]:
        raise ValueError("Rig file has been modified or damaged")
    doc, files = _read_rig(file)
    return aid, asset, file, doc, files


def rig_info(project: Project, character):
    """Return only registered paths/roles, never an arbitrary filename."""
    aid, asset, file, rig, files = _active(project, character)
    sizes = {}
    from PIL import Image
    for part in rig["parts"]:
        with Image.open(files[part["file"]]) as sprite:
            sizes[part["bone"]] = [sprite.width, sprite.height]
    versions = sorted(k for k in asset["files"] if
                      k == "rig.json" or re.fullmatch(r"rig_edit_[0-9a-f]{64}\.json", k))
    return {
        "character": character, "rig": rig, "asset_id": aid,
        "dimensions": sizes,
        "versions": versions,
        "active_version": file.name,
        "warnings": rig_warnings(rig, sizes),
        "source": asset["source"], "license": asset["license"],
    }


def rig_warnings(rig, sizes):
    warnings = []
    parts = rig["parts"]
    if len(parts) != 15:
        warnings.append("Rig must have 15 separate anatomical bone roles")
    for part in parts:
        bone = part["bone"]
        w, h = sizes[bone]
        for field in ("pivot", "source_end"):
            if field not in part:
                continue
            x, y = point(part[field], f"{bone}.{field}")
            if not -w <= x <= 2*w or not -h <= y <= 2*h:
                warnings.append(f"{bone}.{field} is far outside the part artwork")
        if "source_end" in part and math.dist(part["pivot"], part["source_end"]) < 2:
            warnings.append(f"{bone}: pivot and source_end nearly coincide")
    anchors = {**DEFAULT_ANCHORS, **rig.get("anchors", {})}
    if anchors["shoulder_left"][0] >= anchors["shoulder_right"][0]:
        warnings.append("Left/right shoulder anchors are reversed or overlap")
    if anchors["hip_left"][0] >= anchors["hip_right"][0]:
        warnings.append("Left/right hip anchors are reversed or overlap")
    if not rig.get("faces"):
        warnings.append("No authored mouth/eye expression sprites; talking is not production-ready")
    return warnings


def _validate_edit(rig, edit, sizes):
    """Allow finite geometry-only updates; forbid direct file/identity modification."""
    if not isinstance(edit, dict):
        raise ValueError("Rig edit must be a JSON object")
    op = edit.get("kind")
    result = deepcopy(rig)
    if op == "part":
        if set(edit) != {"kind", "bone", "changes"} or edit["bone"] not in sizes:
            raise ValueError("Part edit must identify one existing bone")
        changes = edit["changes"]
        if not isinstance(changes, dict) or not changes or set(changes) - {
            "pivot", "source_end", "depth", "mirror"
        }:
            raise ValueError("Allowed part controls: pivot, source_end, depth, mirror")
        part = next(p for p in result["parts"] if p["bone"] == edit["bone"])
        w, h = sizes[edit["bone"]]
        for key, value in changes.items():
            if key in ("pivot", "source_end"):
                x, y = point(value, f"part.{key}")
                if not -w <= x <= 2*w or not -h <= y <= 2*h:
                    raise ValueError("Pivot/end location outside supported sprite bounds")
                part[key] = [x,y]
            elif key == "depth":
                part[key] = number(value, "part.depth", -1000, 1000)
            elif key == "mirror":
                if type(value) is not bool:
                    raise ValueError("mirror must be boolean")
                part[key] = value
        if "source_end" in part and math.dist(part["pivot"], part["source_end"]) < 2:
            raise ValueError("Bone pivot and source_end cannot coincide")
    elif op == "anchor":
        if set(edit) != {"kind","name","value"} or edit["name"] not in ANCHORS:
            raise ValueError("Unknown anatomical anchor")
        result.setdefault("anchors", {})[edit["name"]] = point(edit["value"], "anchor")
    elif op == "length":
        if set(edit) != {"kind","name","value"} or edit["name"] not in LENGTHS:
            raise ValueError("Unknown bone length")
        result.setdefault("lengths", {})[edit["name"]] = number(edit["value"], "bone length", 5, 2000)
    else:
        raise ValueError("Unsupported rig edit; layer image/part identity is immutable")
    return result


def _activate_version(project, aid, asset, file_name, sha):
    updated = deepcopy(project.doc)
    current = updated["assets"][aid]
    current["path"] = (Path(asset["path"]).parent / file_name).as_posix()
    current["sha256"] = sha
    if file_name not in current["files"]:
        current["files"][file_name] = sha
    before = project.doc
    project.doc = validate_project(updated)
    try:
        project.save()
        project.verify_assets()
    except Exception:
        project.doc = before
        raise


def commit_rig_edit(project: Project, character, edit):
    aid, asset, path, rig, files = _active(project, character)
    sizes = rig_info(project, character)["dimensions"]
    edited = _validate_edit(rig, edit, sizes)
    raw = (json.dumps(edited, sort_keys=True, indent=2,
                      ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")
    import hashlib
    sha = hashlib.sha256(raw).hexdigest()
    name = "rig_edit_" + sha + ".json"
    output = path.parent / name
    created = not output.exists()
    if created:
        with output.open("xb") as f:
            f.write(raw)
    elif output.read_bytes() != raw:
        raise ValueError("Rig version hash collision")
    try:
        _read_rig(output)  # existing full PNG/rig contract, no replacement solver
        _activate_version(project, aid, asset, name, sha)
    except Exception:
        if created:
            output.unlink(missing_ok=True)
        raise
    return rig_info(project, character)


def restore_rig_version(project: Project, character, filename):
    aid, asset, active, rig, files = _active(project, character)
    if not isinstance(filename, str) or filename not in asset["files"] or not (
            filename == "rig.json" or
            re.fullmatch(r"rig_edit_[0-9a-f]{64}\.json", filename)):
        raise ValueError("Unknown/unsafe rig revision")
    path = _contained(active.parent, filename)
    if not path.is_file() or hash_file(path) != asset["files"][filename]:
        raise ValueError("Saved rig version is corrupt")
    _read_rig(path)
    _activate_version(project, aid, asset, filename, asset["files"][filename])
    return rig_info(project, character)


def original_rig_preview(project: Project, character, *, movement=False, size=(600,500)):
    """Use the SAME saved cutout rig and IK renderer as exported movie frames."""
    _, asset, _, rig, _ = _active(project, character)
    from animation2d.episode03.engine import render_frame
    w, h = size
    actor = {"position": [w/2, h*.43], "scale": .65, "depth": 100,
             "foot_lock": True, "actions": []}
    if movement:
        actor["actions"].append({"clip":"reach","hand":"right",
                                 "start":0,"end":1.5,"target":[w*.72,h*.24]})
    data = {"canvas":[w,h],"fps":24,
            "characters":{character:{"rig":asset["path"]}},
            "shots":[{"id":"RIG_TECHNICAL_PREVIEW","duration":2,
                      "cast":[character],"actors":{character:actor},
                      "camera":{"zoom":1,"center":[w/2,h/2]},
                      "props":[],"dialogue":[]}],
            "__base_dir__":str(project.root)}
    return render_frame(data, "RIG_TECHNICAL_PREVIEW", 1 if movement else 0,
                        mode="production",size=size)


def sprite_bytes(project: Project, character, bone):
    _, asset, active, rig, files = _active(project, character)
    part = next((p for p in rig["parts"] if p["bone"] == bone), None)
    if part is None:
        raise ValueError("Unknown bone")
    file = files[part["file"]]
    if file.name not in asset["files"] or hash_file(file) != asset["files"][file.name]:
        raise ValueError("Artwork no longer matches imported checksum")
    return file.read_bytes()
