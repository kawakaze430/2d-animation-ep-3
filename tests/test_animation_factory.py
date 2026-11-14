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

    def test_priority_hand_clip_crossfade_and_slow_hold_continuity(self):
        layers = ActionMixer({"position": [500, 600], "actions": [
            {"clip": "reach", "start": 0, "end": 4, "hand": "right",
             "target": [400, 600], "priority": 0},
            {"clip": "reach", "start": 0, "end": 4, "hand": "right",
             "target": [600, 600], "priority": 10, "weight": .5},
        ]}, 6)
        # Both actions are 50% progressed: 0.5 blend weight times 0.5
        # easing gives 25% transition from prior target to overlay.
        target = layers.sample(2).hand_targets["right"][0]
        np.testing.assert_allclose(target, [450, 600])

        slow = ActionMixer({"position": [500, 600], "actions": [
            {"clip": "reach", "start": 0, "end": 2, "hand": "right",
             "target": [700, 540], "speed": .5, "hold_last": True, "blend": .1}
        ]}, 6)
        near_end = slow.sample(1.999).hand_targets["right"][1]
        held = slow.sample(2.001).hand_targets["right"][1]
        self.assertLess(abs(near_end - held), .01)
        self.assertAlmostEqual(held, .5)
        self.assertIn("reach", slow.sample(4).active)

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

    def test_named_prop_targets_reuse_real_world_coordinates(self):
        # Named object references drive wrist intent rather than being ignored metadata.
        scene = compile_scene(SOURCE, SHOT)["shots"][0]
        props = {p["id"]: p for p in scene["props"]}
        maya = scene["actors"]["MAYA"]
        nina = scene["actors"]["NINA"]
        self.assertEqual(maya["actions"][0]["object"], "recipe_card")
        self.assertEqual(nina["actions"][0]["object"], "blue_bowl")
        target_m = ActionMixer(maya, 15, objects=props).sample(1.5).hand_targets["right"][0]
        target_n = ActionMixer(nina, 15, objects=props).sample(2.0).hand_targets["left"][0]
        np.testing.assert_allclose(target_m, props["recipe_card"]["position"])
        np.testing.assert_allclose(target_n, props["blue_bowl"]["position"])
        # Same reusable reach implementation returns the hands after prop release.
        np.testing.assert_allclose(
            ActionMixer(maya, 15, objects=props).sample(5).hand_targets["right"][0],
            [558, 693])
        np.testing.assert_allclose(
            ActionMixer(nina, 15, objects=props).sample(5).hand_targets["left"][0],
            [1212, 693])
        for actor_name, hand in (("MAYA", "right"), ("NINA", "left")):
            actor = Actor(actor_name, placement=scene["actors"][actor_name], objects=props)
            self.assertTrue(np.isfinite(actor.solved_hand(2, hand).position).all())
        broken = json.loads(SHOT.read_text())
        broken["actors"]["MAYA"]["actions"][0]["object"] = "not_in_this_scene"
        with self.assertRaisesRegex(ValueError, "Unknown action object"):
            compile_scene(SOURCE, broken)

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

    def test_future_episode_new_character_and_variable_duration(self):
        from animation2d.episode03.factory_render import fingerprint, chunk
        config = {
            "version": 1, "shot": "FUTURE_001", "new_story": True,
            "duration": 8, "cast": ["JUNO"],
            "characters": {"JUNO": {"default_scale": .6}},
            "dialogue": [{"speaker": "JUNO", "text": "Welcome to a new story.",
                          "start": .5, "end": 3}],
            "environment": "home_kitchen", "camera": "wide",
            "actors": {"JUNO": {"position": [740, 640], "scale": .6,
                                "actions": [
                                    {"clip": "walk", "start": 0, "end": 3,
                                     "target": [840, 640]},
                                    {"clip": "gesture", "start": 3, "end": 6,
                                     "target": [920, 560]}]}}
        }
        future = compile_scene(SOURCE, config)
        self.assertEqual(future["shots"][0]["id"], "FUTURE_001")
        self.assertEqual(future["shots"][0]["duration"], 8)
        self.assertEqual(future["shots"][0]["cast"], ["JUNO"])
        self.assertEqual(render_frame(future, "FUTURE_001", 7.95, size=(160, 90)).size, (160, 90))
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "future.json"
            manifest.write_text(json.dumps(future))
            signature = fingerprint(manifest, "blocking", size=(160, 90))
            self.assertEqual(signature["duration"], 8)
            part = Path(folder) / "part"
            result = chunk(manifest, "blocking", 0, 2, part, size=(160, 90))
            self.assertEqual(result["count"], 2)
            self.assertTrue((part/"frame_0000.png").exists())
            # Repeated job is a real incremental cache hit, not a re-render.
            self.assertEqual(chunk(manifest, "blocking", 0, 2, part, size=(160, 90))["hashes"],
                             result["hashes"])

    def test_generic_actor_blink_is_visible_in_browser_schematic(self):
        from PIL import Image, ImageChops
        actor = Actor("JUNO", placement={
            "position": [200, 240], "scale": 1,
            "actions": [{"clip": "blink", "start": 0, "end": 1}]
        })
        before, during = Image.new("RGBA", (440, 420)), Image.new("RGBA", (440, 420))
        actor.draw(before, .2, duration=4)
        actor.draw(during, .5, duration=4)
        delta = ImageChops.difference(before.convert("RGB"), during.convert("RGB"))
        self.assertIsNotNone(delta.getbbox())
        self.assertFalse(actor.pose(.2, 4)["blink"])
        self.assertTrue(actor.pose(.5, 4)["blink"])

    def test_original_manifest_remains_unchanged(self):
        initial = SOURCE.read_bytes()
        compile_scene(SOURCE, SHOT)
        self.assertEqual(SOURCE.read_bytes(), initial)


if __name__ == "__main__":
    unittest.main()
