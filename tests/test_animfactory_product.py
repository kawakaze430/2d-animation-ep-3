"""Real technical acceptance tests for the independent animation product.

Synthetic transparent rig art is deliberate: no Episode 03 reference characters,
movie production, AI inference or paid APIs are needed to validate product core.
"""
from __future__ import annotations

from copy import deepcopy
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

from PIL import Image, ImageDraw

from animfactory import Project, EditSession, apply_command
from animfactory.schema import validate_project
from animfactory.studio import handler_for
from animation2d.episode03.engine import Actor, production_readiness
from animation2d.episode03.motion_clips import ClipLibrary
from animation2d.episode03.quality import joint_connections


BONES = {"head", "torso", "pelvis"} | {
    f"{name}.{side}" for name in ("upper_arm", "forearm", "hand", "thigh", "shin", "foot")
    for side in ("left", "right")
}


def synthetic_rig(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    png = Image.new("RGBA", (24, 44), (0, 0, 0, 0))
    art = ImageDraw.Draw(png)
    art.rounded_rectangle((3, 3, 20, 39), radius=5, fill="#CB885E")
    art.ellipse((7, 8, 17, 18), fill="#F0C4B0")
    png.save(directory / "part.png", format="PNG")
    doc = {
        "version": 1,
        "anchors": {"neck": [0,-180]},
        "parts": [{"id": item.replace(".", "_"), "bone": item, "file": "part.png",
                   "pivot": [12,4], "source_end": [12,37],
                   "depth": i} for i,item in enumerate(sorted(BONES))],
        "faces": {},
    }
    (directory / "rig.json").write_text(json.dumps(doc))
    return directory / "rig.json"


class IndependentProductCoreTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.source = synthetic_rig(self.root / "original")
        self.project = Project.create(self.root / "project", "story_001", "A New Story",
                                      canvas=(160, 90), fps=12)

    def ready(self, with_second=True):
        self.project.import_rig(self.source, "JUNO", license_label="original-user-art")
        if with_second:
            self.project.import_rig(self.source, "RIVER", license_label="original-user-art")
        self.project.add_scene("opening", 24)
        self.project.add_actor("opening", "JUNO", "JUNO", (60, 30), .30)
        self.project.add_action("opening", "JUNO", "hello_1", "keyframed", 0, 14,
                                source="greet")
        if with_second:
            self.project.add_actor("opening", "RIVER", "RIVER", (120, 30), .42)
            self.project.add_action("opening", "RIVER", "hello_2", "keyframed", 0, 14,
                                    source="greet")
        return self.project

    def test_project_is_fully_new_and_not_an_episode03_story(self):
        doc=self.project.doc
        self.assertEqual(doc["format"], "animfactory.project")
        self.assertEqual(doc["version"], 1)
        self.assertFalse(doc["scenes"])
        self.assertIn("greet", doc["motion_library"]["clips"])
        self.assertNotIn("SHOT_001", json.dumps(doc))
        self.assertEqual(Project.open(self.project.root).doc, doc)
        with self.assertRaisesRegex(ValueError, "migration needed"):
            broken=deepcopy(doc);broken["version"]=2;validate_project(broken)

    def test_imported_two_characters_share_one_clip_and_actual_png_renderer(self):
        project=self.ready()
        self.assertTrue(project.verify_assets())
        self.assertEqual(len(project.doc["characters"]),2)
        self.assertEqual(len(project.doc["assets"]),2)
        manifest=project.compile_scene("opening")
        self.assertEqual(len(manifest["shots"][0]["cast"]),2)
        self.assertEqual(production_readiness(manifest,"opening"),[])
        self.assertEqual(manifest["motion_library"],project.doc["motion_library"])
        frame_a=project.render_frame("opening",0,size=(160,90),mode="production")
        frame_b=project.render_frame("opening",6,size=(160,90),mode="production")
        self.assertEqual(frame_a.size,frame_b.size)
        self.assertNotEqual(frame_a.tobytes(),frame_b.tobytes())
        library=ClipLibrary(project.doc["motion_library"])
        pose=[]
        for name in ("JUNO","RIVER"):
            position=manifest["shots"][0]["actors"][name]
            actor=Actor(name,manifest["characters"][name],position,mode="production",
                        base_dir=project.root,library=library)
            actual=actor.pose(.5,2)
            self.assertIn("keyframed",actual["active_actions"])
            self.assertLess(max(joint_connections(actual).values()),1e-5)
            pose.append(actual)
        self.assertNotEqual(pose[0]["root"].tolist(),pose[1]["root"].tolist())
        np=__import__("numpy")
        np.testing.assert_allclose(
            (pose[0]["hands"]["right"].position-pose[0]["root"])/.30,
            (pose[1]["hands"]["right"].position-pose[1]["root"])/.42,atol=1e-5)

    def test_imports_preserve_provenance_and_refuse_corrupt_or_unsafe_rigs(self):
        asset=self.project.import_rig(self.source,"JUNO",license_label="CC0-1.0",source_label="synthetic-test")
        entry=self.project.doc["assets"][asset]
        self.assertEqual(entry["license"],"CC0-1.0")
        self.assertEqual(entry["source"],"synthetic-test")
        self.assertEqual(set(entry["files"]),{"rig.json","part.png"})
        with self.assertRaises(FileExistsError):
            self.project.import_rig(self.source,"JUNO")
        with self.assertRaises(ValueError):
            bad=deepcopy(self.project.doc)
            bad["assets"][asset]["path"]="../../etc/passwd"
            validate_project(bad)
        image=next((self.project.root/"assets"/"rigs"/"JUNO").glob("*.png"))
        image.write_bytes(b"not a real png")
        with self.assertRaisesRegex(ValueError, "corrupted rig layer"):
            Project.open(self.project.root)
        with self.assertRaisesRegex(ValueError, "corrupted rig layer"):
            self.project.verify_assets()

    def test_bad_import_does_not_change_project_data(self):
        doc=json.loads(self.source.read_text())
        doc["parts"].pop()
        self.source.write_text(json.dumps(doc))
        before=self.project.doc
        with self.assertRaisesRegex(ValueError,"missing required bones"):
            self.project.import_rig(self.source,"BROKEN")
        self.assertEqual(before,self.project.doc)
        self.assertFalse((self.project.root/"assets"/"rigs"/"BROKEN").exists())

    def test_editor_batch_undo_redo_validation_and_disk_atomicity(self):
        self.ready(False)
        session=EditSession(self.project)
        before=deepcopy(self.project.doc)
        command={"op":"batch","commands":[
            {"op":"set","path":"/scenes/0/actors/0/position","value":[44,45]},
            {"op":"set","path":"/scenes/0/actors/0/scale","value":.4}
        ]}
        session.apply(command)
        self.assertEqual(self.project.doc["scenes"][0]["actors"][0]["position"],[44,45])
        self.assertTrue(session.can_undo)
        session.undo()
        self.assertEqual(self.project.doc,before)
        self.assertEqual(Project.open(self.project.root).doc,before)
        session.redo()
        self.assertEqual(self.project.doc["scenes"][0]["actors"][0]["scale"],.4)
        self.assertEqual(Project.open(self.project.root).doc,self.project.doc)
        old=deepcopy(self.project.doc)
        with self.assertRaises(ValueError):
            session.apply({"op":"batch","commands":[
                {"op":"set","path":"/scenes/0/actors/0/scale","value":.5},
                {"op":"set","path":"/scenes/0/actors/0/scale","value":-1}
            ]})
        self.assertEqual(self.project.doc,old)
        self.assertEqual(Project.open(self.project.root).doc,old)
        with self.assertRaises(PermissionError):
            apply_command(old,{"op":"set","path":"/assets/JUNO_rig/license","value":"stolen"})
        with self.assertRaises(ValueError):
            apply_command(old,{"op":"set","path":"/scenes/0/actors/0/actions/0/start_frame",
                               "value":1000})

    def test_arbitrary_file_paths_and_unsafe_prop_refs_rejected(self):
        self.ready(False)
        doc=deepcopy(self.project.doc)
        doc["scenes"][0]["props"].append({"id":"inject","file":"/etc/shadow","position":[5,5]})
        with self.assertRaisesRegex(ValueError,"raw file paths forbidden"):
            validate_project(doc)
        doc=deepcopy(self.project.doc)
        doc["scenes"][0]["actors"][0]["actions"][0]["object"]="missing_prop"
        with self.assertRaisesRegex(ValueError,"missing prop"):
            validate_project(doc)
        doc=deepcopy(self.project.doc)
        doc["scenes"][0]["actors"][0]["actions"][0]["evil_module"]="exec"
        with self.assertRaisesRegex(ValueError,"unknown action"):
            validate_project(doc)

    def test_image_import_background_and_compilation(self):
        image=Image.new("RGB",(160,90),(42,67,98))
        image.save(self.root/"backdrop.png")
        asset=self.project.import_image(self.root/"backdrop.png","sky",kind="background",license_label="original")
        self.assertEqual(self.project.doc["assets"][asset]["kind"],"background")
        self.project.add_scene("opening",12)
        editor=EditSession(self.project)
        editor.apply({"op":"add","path":"/scenes/0/background_asset","value":"sky"})
        self.assertEqual(self.project.compile_scene("opening")["shots"][0]["background"],
                         "assets/images/sky.png")
        self.assertEqual(self.project.render_frame("opening",0,mode="blocking").size,(160,90))

    def test_local_studio_api_get_preview_edit_revision_and_undo(self):
        self.ready(False)
        server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(self.project))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(3)))
        conn=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=10)
        self.addCleanup(conn.close)
        def fetch(method,path,payload=None,headers=None):
            body=None if payload is None else json.dumps(payload).encode()
            conn.request(method,path,body=body,headers=headers or {})
            response=conn.getresponse()
            return response.status,response.read()
        status,body=fetch("GET","/api/project")
        self.assertEqual(status,200)
        doc=json.loads(body)
        self.assertEqual(doc["project"]["id"],"story_001")
        status,image=fetch("GET","/api/frame?scene=opening&index=0&mode=production")
        self.assertEqual(status,200)
        self.assertTrue(image.startswith(b"\x89PNG"))
        self.assertEqual(fetch("GET","/../../etc/passwd")[0],404)
        payload={"revision":doc["revision"],"command":{
            "op":"set","path":"/scenes/0/actors/0/position","value":[71,41]}}
        status,body=fetch("POST","/api/edit",payload,{"Content-Type":"application/json"})
        self.assertEqual(status,200)
        current=json.loads(body)
        self.assertTrue(current["undo"])
        self.assertEqual(current["project"]["scenes"][0]["actors"][0]["position"],[71,41])
        self.assertEqual(fetch("POST","/api/edit",payload,{"Content-Type":"application/json"})[0],409)
        status,body=fetch("POST","/api/undo",{"revision":current["revision"]},{"Content-Type":"application/json"})
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)["project"]["scenes"][0]["actors"][0]["position"],[60,30])
        self.assertEqual(fetch("POST","/api/undo",{"revision":"a"},{"Content-Type":"text/plain"})[0],415)

    def test_short_real_ffmpeg_export_never_calls_providers(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("FFmpeg not available locally")
        self.ready(False)
        from animfactory.cli import _encode_video
        output=self.root/"sample.mp4"
        import subprocess
        from unittest.mock import patch
        real_spawn = subprocess.Popen
        observed = []
        def spawn(*args, **kwargs):
            process = real_spawn(*args, **kwargs)
            observed.append(process)
            return process
        with patch("animfactory.cli.subprocess.Popen", side_effect=spawn):
            result=_encode_video(self.project,"opening",output,mode="blocking",frame_limit=3)
        encoders=[p for p in observed if p.args[0]=="ffmpeg"]
        # FFprobe is intentionally a second subprocess used for media QA.
        self.assertEqual(len(encoders),1)
        self.assertIsNotNone(encoders[0].returncode)
        self.assertTrue(encoders[0].stdin.closed)
        self.assertTrue(encoders[0].stderr.closed)
        self.assertEqual(result["frames"],3)
        self.assertEqual(result["audio"],"none")
        self.assertEqual(result["status"],"SCHEMATIC_BLOCKING_TECHNICAL_ONLY")
        self.assertTrue(output.is_file())
        self.assertTrue(output.with_name(output.name+".json").is_file())
        with self.assertRaises(FileExistsError):
            _encode_video(self.project,"opening",output,mode="blocking",frame_limit=3)


if __name__=="__main__":
    unittest.main()
