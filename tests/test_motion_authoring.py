"""Project-owned keyframe authoring: reuse same saved curve on two original rigs.

The test deliberately does NOT depend on Episode03 story data or a third-party
AI provider. Both characters render using the ORIGINAL Pillow/IK engine.
"""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
import http.client
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import unittest

from PIL import Image, ImageDraw

from animfactory import Project, EditSession
from animfactory.rigging import PARTS, import_layers
from animfactory.studio import handler_for
from animation2d.episode03.engine import Actor
from animation2d.episode03.motion_clips import ClipLibrary
from animation2d.episode03.quality import joint_connections


def artwork():
    img=Image.new("RGBA",(30,48),(0,0,0,0))
    d=ImageDraw.Draw(img)
    d.ellipse((7,6,23,41),fill="#9d70b9")
    buf=BytesIO();img.save(buf,format="PNG")
    return {role:buf.getvalue() for role in PARTS}


class BrowserMotionAuthoringTests(unittest.TestCase):
    def setUp(self):
        self.scratch=tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        self.root=Path(self.scratch.name)
        self.project=Project.create(self.root/"film","motion_factory","Reusable Motion",
                                    canvas=(160,90),fps=12)

    def build_two_rigs(self):
        parts=artwork()
        import_layers(self.project,"ALEX",parts,source="synthetic",license="original")
        import_layers(self.project,"BLAIR",parts,source="synthetic",license="original")
        self.project.add_scene("meeting",24)
        self.project.add_actor("meeting","ALEX","ALEX",(38,30),.28)
        self.project.add_actor("meeting","BLAIR","BLAIR",(130,32),.38)

    @staticmethod
    def custom():
        return {"duration":2.0,"loop":False,"tags":["author-made","conversation"],
                "tracks":{
                    "right_x":{"mode":"smooth","keys":[[0,65],[.4,115],[1,75]]},
                    "right_y":{"mode":"linear","keys":[[0,-20],[.5,-150],[1,-40]]},
                    "head_turn":{"mode":"smooth","keys":[[0,0],[.5,12],[1,0]]},
                }}

    def test_new_named_clip_reuses_real_ik_on_two_rigs_and_persists(self):
        self.build_two_rigs()
        session=EditSession(self.project)
        session.apply({"op":"add","path":"/motion_library/clips/my_hello","value":self.custom()})
        for name in ("ALEX","BLAIR"):
            self.project.add_action("meeting",name,"wave_"+name,"keyframed",0,24,source="my_hello")
        compiled=self.project.compile_scene("meeting")
        library=ClipLibrary(compiled["motion_library"])
        normalized=[]
        for name in ("ALEX","BLAIR"):
            actor=Actor(name,compiled["characters"][name],
                        compiled["shots"][0]["actors"][name],mode="production",
                        base_dir=self.project.root,library=library)
            pose=actor.pose(.9,2.0)
            self.assertIn("keyframed",pose["active_actions"])
            self.assertLess(max(joint_connections(pose).values()),1e-5)
            normalized.append((pose["hands"]["right"].position-pose["root"])/pose["scale"])
        import numpy as np
        np.testing.assert_allclose(normalized[0],normalized[1],atol=1e-5)
        first=self.project.render_frame("meeting",0,mode="production")
        middle=self.project.render_frame("meeting",9,mode="production")
        self.assertNotEqual(first.tobytes(),middle.tobytes())
        reopened=Project.open(self.project.root)
        self.assertEqual(reopened.doc["motion_library"]["clips"]["my_hello"],self.custom())
        self.assertEqual(reopened.render_frame("meeting",9,mode="production").tobytes(),
                         middle.tobytes())

    def test_curve_edit_changes_both_actors_but_not_original_sprite_files(self):
        self.build_two_rigs()
        session=EditSession(self.project)
        session.apply({"op":"add","path":"/motion_library/clips/my_hello","value":self.custom()})
        for name in ("ALEX","BLAIR"):
            self.project.add_action("meeting",name,"wave_"+name,"keyframed",0,24,source="my_hello")
        before=self.project.render_frame("meeting",9,mode="production").tobytes()
        doc=deepcopy(self.project.doc)
        changes=deepcopy(self.custom())
        changes["tracks"]["right_x"]["keys"][1][1]=220
        session.apply({"op":"set","path":"/motion_library/clips/my_hello","value":changes})
        after=self.project.render_frame("meeting",9,mode="production").tobytes()
        self.assertNotEqual(before,after)
        session.undo()
        self.assertEqual(self.project.render_frame("meeting",9,mode="production").tobytes(),before)
        session.redo()
        self.assertEqual(self.project.render_frame("meeting",9,mode="production").tobytes(),after)
        self.assertEqual(Project.open(self.project.root).doc,self.project.doc)
        self.assertTrue(self.project.verify_assets())

    def test_invalid_curves_rejected_transactionally(self):
        session=EditSession(self.project)
        baseline=deepcopy(self.project.doc)
        bad=[
            {"duration":2,"loop":False,"tracks":{"right_x":{
                "keys":[[.5,20],[.5,40]]}}},
            {"duration":1,"loop":True,"tracks":{"head_turn":{
                "keys":[[0,0],[1,3]]}}},
            {"duration":1,"loop":False,"tracks":{"evil_python":{
                "keys":[[0,0],[1,5]]}}},
            {"duration":1,"loop":False,"tracks":{"blink":{
                "mode":"invalid","keys":[[0,0],[1,1]]}}},
            {"duration":-1,"loop":False,"tracks":{"blink":{
                "keys":[[0,0],[1,1]]}}},
        ]
        for definition in bad:
            with self.subTest(definition=definition),self.assertRaises(ValueError):
                session.apply({"op":"add","path":"/motion_library/clips/unsafe",
                               "value":definition})
            self.assertEqual(self.project.doc,baseline)
            self.assertEqual(Project.open(self.project.root).doc,baseline)
        self.assertFalse(session.can_undo)

    def test_existing_project_and_source_pose_regression_stays_intact(self):
        from animation2d.episode03.motion_clips import default_library
        self.assertIn("greet",self.project.doc["motion_library"]["clips"])
        sample=default_library().sample("keyframed","greet",.5)
        self.assertEqual(sample,ClipLibrary(self.project.doc["motion_library"])
                         .sample("keyframed","greet",.5))
        self.assertEqual(default_library().sample("pose","hold_tray",0),
                         ClipLibrary(self.project.doc["motion_library"])
                         .sample("pose","hold_tray",0))

    def test_browser_receives_real_curve_ui_and_allows_valid_clip_edit(self):
        session=EditSession(self.project)
        server=ThreadingHTTPServer(("127.0.0.1",0),handler_for(self.project))
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(3)))
        connection=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=10)
        self.addCleanup(connection.close)
        def req(method,path,data=None):
            body=None if data is None else json.dumps(data).encode()
            headers={} if data is None else {"Content-Type":"application/json"}
            connection.request(method,path,body=body,headers=headers)
            r=connection.getresponse();return r.status,r.read()
        status,data=req("GET","/curves.js")
        self.assertEqual(status,200)
        self.assertIn(b"curveStartDrag",data)
        status,data=req("GET","/api/project")
        self.assertEqual(status,200)
        snap=json.loads(data)
        status,data=req("POST","/api/edit",{"revision":snap["revision"],
          "command":{"op":"add","path":"/motion_library/clips/my_hello",
                     "value":self.custom()}})
        self.assertEqual(status,200,data)
        changed=json.loads(data)
        self.assertIn("my_hello",changed["project"]["motion_library"]["clips"])
        self.assertTrue(changed["undo"])
        status,data=req("POST","/api/undo",{"revision":changed["revision"]})
        self.assertEqual(status,200)
        self.assertNotIn("my_hello",json.loads(data)["project"]["motion_library"]["clips"])


if __name__=="__main__":
    unittest.main()
