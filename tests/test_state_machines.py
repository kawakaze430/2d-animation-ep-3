"""Seekable state machines use existing procedural/keyframe actions and IK.

No mutable playhead, Python script snippets, or AI provider in saved project.
"""
from __future__ import annotations

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from animfactory import Project, EditSession
from animfactory.rigging import PARTS, import_layers
from animfactory.states import validate_graph, compile_machine
from animation2d.episode03.actions import ActionMixer


def test_art():
    p=Image.new("RGBA",(30,54),(0,0,0,0))
    ImageDraw.Draw(p).rounded_rectangle((6,4,23,48),radius=4,fill="#a57e71")
    output=BytesIO();p.save(output,format="PNG")
    return {bone:output.getvalue() for bone in PARTS}


def graph():
    return {"version":1,
            "states":{
                "idle":{"actions":[{"clip":"idle"}]},
                "walk":{"actions":[{"clip":"walk","target":[100,32],"hold_last":True}]},
                "reach":{"actions":[{"clip":"reach","target":[100,10],"hand":"right",
                                      "hold_last":True}]},
                "hold":{"actions":[{"clip":"hold","target":[100,10],"hand":"right",
                                     "hold_last":True}]},
                "release":{"actions":[{"clip":"put_down","target":[110,38],
                                        "hand":"right","hold_last":True}]},
                "talking":{"actions":[{"clip":"talk","emotion":"happy"},
                                      {"clip":"blink"}]},
            },
            "allowed_transitions":[
                ["idle","walk"],["walk","reach"],["reach","hold"],["hold","release"],
                ["release","idle"]
            ]}


def schedule(target_walk=(100,32), target_hand=(100,10)):
    return {"source":"common_interaction",
            "steps":[
                {"at_frame":0,"state":"idle"},
                {"at_frame":4,"state":"walk","params":{"target":list(target_walk)}},
                {"at_frame":11,"state":"reach",
                 "params":{"target":list(target_hand)},"blend_frames":1},
                {"at_frame":13,"state":"talking","mode":"overlay","duration_frames":4},
                {"at_frame":16,"state":"hold","params":{"target":list(target_hand)}},
                {"at_frame":20,"state":"release","params":{"target":[110,38]}},
            ]}


class DeclarativeStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.project=Project.create(Path(self.tmp.name)/"project","state_product",
                                    "A New State Story",canvas=(160,90),fps=12)

    def setup_scene(self):
        pngs=test_art()
        import_layers(self.project,"ALEX",pngs)
        import_layers(self.project,"BLAIR",pngs)
        self.project.add_scene("hello",24)
        self.project.add_actor("hello","ALEX","ALEX",(38,32),.30)
        self.project.add_actor("hello","BLAIR","BLAIR",(125,32),.40)
        editor=EditSession(self.project)
        editor.apply({"op":"add","path":"/motion_library/machines/common_interaction",
                      "value":graph()})
        editor.apply({"op":"add","path":"/scenes/0/actors/0/machine",
                      "value":schedule((80,32),(95,25))})
        editor.apply({"op":"add","path":"/scenes/0/actors/1/machine",
                      "value":schedule((137,32),(140,25))})
        return editor

    def test_two_characters_reuse_single_graph_and_seek_deterministically(self):
        self.setup_scene()
        doc=self.project.doc
        self.assertEqual(set(doc["motion_library"]["machines"]),{"common_interaction"})
        scene=self.project.compile_scene("hello")
        tracks=scene["shots"][0]["actors"]
        for name in ("ALEX","BLAIR"):
            self.assertEqual([x["clip"] for x in tracks[name]["actions"]],
                             ["idle","walk","reach","talk","blink","hold","put_down"])
            self.assertEqual(len(tracks[name]["actions"]),7)
            self.assertEqual(tracks[name]["actions"][2]["blend"],1/12)
        cache={}
        for frame in (17,0,23,5,12,2,17,5,12,23):
            data=self.project.render_frame("hello",frame,mode="production").tobytes()
            if frame in cache:
                self.assertEqual(cache[frame],data)
            cache[frame]=data
        self.assertNotEqual(cache[0],cache[12])
        self.assertEqual(Project.open(self.project.root).doc,doc)
        self.assertEqual(Project.open(self.project.root).render_frame(
            "hello",17,mode="production").tobytes(),cache[17])

    def test_action_mixer_preserves_walk_root_after_transition_to_reach(self):
        self.setup_scene()
        manifest=self.project.compile_scene("hello")
        actor=manifest["shots"][0]["actors"]["ALEX"]
        mixer=ActionMixer(actor,2,objects={})
        x0=mixer.sample(0)["root"] if isinstance(mixer.sample(0),dict) else mixer.sample(0).root
        x1=mixer.sample(15/12).root
        x2=mixer.sample(22/12).root
        self.assertGreater(x1[0],x0[0])
        self.assertAlmostEqual(x1[0],x2[0],delta=.1)
        self.assertIn("reach",mixer.sample(12/12).active)
        self.assertIn("talk",mixer.sample(14/12).active)

    def test_invalid_transitions_and_bad_times_reject_transactionally(self):
        editor=self.setup_scene()
        before=deepcopy(self.project.doc)
        bads=[
            {"source":"common_interaction","steps":[
                {"at_frame":0,"state":"idle"},
                {"at_frame":4,"state":"release"}]},
            {"source":"common_interaction","steps":[
                {"at_frame":0,"state":"idle"},
                {"at_frame":2,"state":"walk"},
                {"at_frame":2,"state":"reach"}]},
            {"source":"common_interaction","steps":[
                {"at_frame":0,"state":"idle"},
                {"at_frame":3,"state":"walk","blend_frames":5}]},
            {"source":"common_interaction","steps":[
                {"at_frame":0,"state":"idle"},
                {"at_frame":3,"state":"walk","params":{"evil_python":"execute"}}]},
            {"source":"wrong_source","steps":[{"at_frame":0,"state":"idle"}]},
        ]
        for value in bads:
            with self.subTest(value=value),self.assertRaises(ValueError):
                editor.apply({"op":"set","path":"/scenes/0/actors/0/machine","value":value})
            self.assertEqual(self.project.doc,before)

    def test_source_graph_is_independent_of_character_and_supports_undo(self):
        editor=self.setup_scene()
        previous=deepcopy(self.project.doc)
        new=deepcopy(graph())
        new["states"]["reach"]["actions"][0]["target"]=[120,18]
        editor.apply({"op":"set","path":"/motion_library/machines/common_interaction","value":new})
        self.assertNotEqual(self.project.doc,previous)
        self.assertEqual(self.project.doc["scenes"][0]["actors"][0]["machine"],
                         previous["scenes"][0]["actors"][0]["machine"])
        editor.undo()
        self.assertEqual(self.project.doc,previous)
        editor.redo()
        self.assertEqual(self.project.doc["motion_library"]["machines"]["common_interaction"],new)

    def test_compatibility_with_old_projects_without_machine_registry(self):
        old=deepcopy(self.project.doc)
        del old["motion_library"]["machines"]
        from animfactory.schema import validate_project
        self.assertEqual(validate_project(old),old)
        self.assertEqual(compile_machine(schedule(),{
            "machines":{"common_interaction":graph()}
        },12,24)[0]["clip"],"idle")
        bad=graph();bad["states"]["idle"]["actions"]=[{"clip":"arbitrary_shell"}]
        with self.assertRaises(ValueError):
            validate_graph(bad)


if __name__=="__main__":
    unittest.main()
