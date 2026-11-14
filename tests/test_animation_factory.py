"""Guard compatibility, reusable action states, honest production readiness and scene isolation."""
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from animation2d.episode03.actions import ActionMixer, LIBRARY, shared_clip_demo
from animation2d.episode03.engine import Actor, production_readiness, render_frame, REPO
from animation2d.episode03.scene_factory import compile_scene
from animation2d.episode03.factory_demo import manifest_for_demo

SOURCE = REPO / "animation2d/episode03/shots.json"
SHOT = REPO / "animation2d/episode03/factory/scenes/SHOT_001.json"


class ReusableFactoryTests(unittest.TestCase):
    def test_all_action_types_sample_from_one_engine(self):
        self.assertGreaterEqual(len(LIBRARY), 16)
        for clip in LIBRARY:
            with self.subTest(clip=clip):
                placement = {"position": [800, 600], "actions": [{
                    "clip": clip, "start": 0, "end": 4, "hand": "left",
                    "target": [700, 530], "emotion": "happy",
                }]}
                s = ActionMixer(placement, 15).sample(2)
                self.assertIn(clip, s.active)
                self.assertTrue(np.isfinite(s.root).all())
                if LIBRARY[clip] == "hands":
                    self.assertIn("left", s.hand_targets)
                if clip == "run":
                    self.assertTrue(s.running)
                if clip == "sit":
                    self.assertGreater(s.sitting, 0)

    def test_parallel_blending_and_state_transitions(self):
        mix = ActionMixer({"position": [400, 600], "actions": [
            {"clip": "walk", "start": 0, "end": 4, "target": [600, 600]},
            {"clip": "talk", "start": 1, "end": 5},
            {"clip": "reach", "start": 2, "end": 3, "hand": "left", "target": [800, 500],
             "hold_last": True, "blend": .1},
            {"clip": "look", "start": 2, "end": 6, "degrees": 10},
        ]}, 10)
        before = mix.sample(.5)
        during = mix.sample(2.5)
        after = mix.sample(8)
        self.assertGreater(during.root[0], before.root[0])
        self.assertTrue(during.speaking)
        self.assertIn("left", during.hand_targets)
        self.assertAlmostEqual(after.root[0], 600)
        self.assertFalse(after.speaking)
        self.assertIn("left", after.hand_targets)
        self.assertEqual(mix.sample(2.5).hand_targets["left"][1], during.hand_targets["left"][1])

    def test_invalid_actions_are_rejected_early(self):
        invalid = [
            {"clip": "teleport", "start": 0, "end": 1},
            {"clip": "reach", "start": 5, "end": 3},
            {"clip": "reach", "start": 0, "end": 4, "target": ["bad", 50]},
            {"clip": "walk", "start": 0, "end": 3, "weight": 1.5},
            {"clip": "blink", "start": 0, "end": 1, "blend": 1},
        ]
        for spec in invalid:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                ActionMixer({"actions": [spec]}, 15)

    def test_same_action_code_three_people_different_shots(self):
        manifest = manifest_for_demo(SOURCE)
        self.assertEqual(len(manifest["shots"]), 3)
        self.assertEqual({s["id"] for s in manifest["shots"]},
                         {"DEMO_000", "DEMO_001", "DEMO_002"})
        baseline = []
        for shot in manifest["shots"]:
            name = shot["cast"][0]
            actor = Actor(name, placement=shot["actors"][name])
            pose = actor.pose(1.0)
            baseline.append(pose["hands"]["right"].position)
            self.assertEqual(pose["active_actions"], ("reach", "look", "blink"))
        self.assertEqual(len({tuple(x) for x in baseline}), 3)
        # Preview is visibly schematic; a demo is not labelled a production movie.
        frame = render_frame(manifest, "DEMO_001", 1, size=(320, 180))
        self.assertEqual(frame.size, (320, 180))

    def test_exact_shot001_screenplay_is_immutable_and_prop_contact_is_validated(self):
        base = json.loads(SOURCE.read_text())
        source_dialogue = next(s for s in base["shots"] if s["id"] == "SHOT_001")["dialogue"]
        compiled = compile_scene(base, SHOT)
        shot = compiled["shots"][0]
        self.assertEqual(shot["dialogue"], source_dialogue)
        self.assertEqual(len(shot["cast"]), 3)
        self.assertEqual(shot["duration"], 15)
        self.assertEqual(compiled["fps"], 24)
        self.assertEqual(compiled["canvas"], [1920, 1080])
        self.assertEqual(shot["camera"]["zoom"], 1)
        self.assertEqual(shot["actors"]["NINA"]["actions"][0]["hand"], "left")
        self.assertEqual(shot["actors"]["MAYA"]["actions"][0]["clip"], "reach")
        self.assertIn("recipe_stand", {p["id"] for p in shot["props"]})
        self.assertIn("interaction", next(p for p in shot["props"] if p["id"]=="blue_bowl"))
        self.assertEqual(len(base["shots"]), 80)
        self.assertEqual(len(production_readiness(compiled, "SHOT_001")), 3)

    def test_invalid_object_binding_rejects_wrong_cast_and_teleport(self):
        config = json.loads(SHOT.read_text())
        for p in config["props"]:
            if p["id"] == "blue_bowl":
                p["interaction"]["landing"] = [300, 100]
        with self.assertRaisesRegex(ValueError, "teleport"):
            compile_scene(SOURCE, config)
        for p in config["props"]:
            if p["id"] == "blue_bowl":
                p["interaction"]["actor"] = "UNKNOWN"
        with self.assertRaisesRegex(ValueError, "visible actor"):
            compile_scene(SOURCE, config)

    def test_original_manifest_remains_unchanged(self):
        initial = SOURCE.read_bytes()
        compile_scene(SOURCE, SHOT)
        self.assertEqual(SOURCE.read_bytes(), initial)


if __name__ == "__main__":
    unittest.main()
