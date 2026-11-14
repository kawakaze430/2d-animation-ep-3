"""Cross-cast clip reuse, PySpine-inspired rig QA and modern scene rendering tests."""
from __future__ import annotations

import copy
import json
import math
import unittest

import numpy as np
from PIL import Image

from animation2d.episode03.actions import ActionMixer
from animation2d.episode03.camera_clips import sample_camera, validate_camera_tracks
from animation2d.episode03.engine import Actor, render_frame
from animation2d.episode03.motion_clips import ClipLibrary, default_library
from animation2d.episode03.quality import joint_connections, foot_sliding, hand_prop_release_error
from animation2d.episode03.scene_factory import compile_scene
from animation2d.episode03.engine import REPO

SCENE = REPO / "animation2d/episode03/factory/scenes/SHOT_001.json"
MANIFEST = REPO / "animation2d/episode03/shots.json"


class SkeletalClipLibraryTests(unittest.TestCase):
    def test_named_clips_and_poses_do_not_require_actor_art(self):
        lib = default_library()
        self.assertIn("stir_cycle", lib.clips)
        self.assertIn("sit_down", lib.clips)
        self.assertIn("hold_tray", lib.poses)
        self.assertEqual(lib.sample("pose", "seated", 100)["sitting"], 1)
        self.assertEqual(lib.sample("keyframed", "greet", 0)["head_turn"], 0)
        self.assertEqual(lib.sample("keyframed", "stir_cycle", 0),
                         lib.sample("keyframed", "stir_cycle", 4))

    def test_clip_sampling_step_smooth_loop_and_untrusted_input(self):
        lib = ClipLibrary({"version": 1, "clips": {
            "custom": {"duration": 2, "tracks": {
                "head_turn": {"mode": "linear", "keys": [[0, 0], [.5, 20], [1, 40]]},
                "lean": {"mode": "step", "keys": [[0, 0], [.5, 9], [1, 0]]},
            }}
        }, "poses": {"relaxed": {"left_x": -50, "left_y": 60}}})
        self.assertEqual(lib.sample("keyframed", "custom", .5)["head_turn"], 10)
        self.assertEqual(lib.sample("keyframed", "custom", 1)["lean"], 9)
        self.assertEqual(lib.sample("keyframed", "custom", 100)["head_turn"], 40)
        self.assertEqual(lib.sample("pose", "relaxed", 0)["left_x"], -50)
        invalid = [
            {"version": 3, "clips": {}},
            {"version": 1, "clips": {"oops": {"duration": 1, "tracks": {"teleport": {"keys": [[0, 1]]}}}}},
            {"version": 1, "clips": {"oops": {"duration": 1, "tracks": {"lean": {"keys": [[0, 1], [0, 2]]}}}}},
            {"version": 1, "clips": {"oops": {"duration": 1, "tracks": {"lean": {"keys": [[0, 0], [1, 2]]}}, "loop": True}}},
            {"version": 1, "clips": {"oops": {"duration": float("nan"), "tracks": {"lean": {"keys": [[0, 0]]}}}}},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                ClipLibrary(value)

    def test_same_named_keyframed_clip_is_parameterized_across_three_rigs(self):
        starts = {"DAN": ([180, 400], .45), "MAYA": ([900, 580], .63),
                  "NINA": ([1400, 690], .8)}
        normalized = []
        for name, (start, scale) in starts.items():
            placement = {"position": start, "scale": scale,
                         "actions": [
                             {"clip": "keyframed", "source": "greet", "start": 0, "end": 1.2},
                             {"clip": "talk", "start": .2, "end": 1.0, "emotion": "happy"},
                         ]}
            actor = Actor(name, placement=placement)
            pose = actor.pose(.6, 3)
            self.assertEqual(pose["active_actions"], ("keyframed", "talk"))
            self.assertIn("right", pose["hands"])
            self.assertLess(max(joint_connections(pose).values()), 1e-6)
            normalized.append((pose["hands"]["right"].position - pose["root"]) / scale)
        for right in normalized[1:]:
            np.testing.assert_allclose(right, normalized[0], atol=1e-4)

    def test_sitting_and_pose_library_use_current_actor_scale(self):
        for scale in (.4, .6, 1.0):
            actor = Actor("DAN", placement={"position": [400, 500], "scale": scale,
                "actions": [{"clip": "keyframed", "source": "sit_down",
                             "start": 0, "end": 1.4, "hold_last": True},
                            {"clip": "pose", "source": "hold_tray",
                             "start": 1.4, "end": 3, "hold_last": True}]})
            pose = actor.pose(2, 4)
            self.assertLess(max(joint_connections(pose).values()), 1e-6)
            self.assertTrue(np.isfinite(pose["joints"]["ankle_right"]).all())
        with self.assertRaisesRegex(ValueError, "Unknown shared motion clip"):
            ActionMixer({"actions": [{"clip": "keyframed", "source": "nonexistent",
                                     "start": 0, "end": 2}]}, 4)

    def test_named_motion_demo_reuses_identical_clip_across_three_shots(self):
        from animation2d.episode03.factory_demo import manifest_for_demo
        manifest = manifest_for_demo(MANIFEST, named_motion="greet")
        self.assertEqual(len(manifest["shots"]), 3)
        signatures = set()
        for shot in manifest["shots"]:
            actor = shot["cast"][0]
            actions = shot["actors"][actor]["actions"]
            self.assertEqual(actions, [{"clip": "keyframed", "source": "greet",
                                        "start": 0, "end": 1.2}])
            signatures.add((actions[0]["clip"], actions[0]["source"]))
            image = render_frame(manifest, shot["id"], .6, size=(320, 180))
            self.assertEqual(image.size, (320, 180))
        self.assertEqual(signatures, {("keyframed", "greet")})

    def test_foot_lock_checks_actual_solved_ankle_not_just_targets(self):
        for scale in (.45, .6, .85):
            placement = {"position": [10, 420], "scale": scale, "foot_lock": True,
                "actions": [{"clip": "walk", "start": 0, "end": 5,
                             "target": [175, 420]}]}
            actor = Actor("DAN", placement=placement)
            for side in ("left", "right"):
                data = foot_sliding(actor, 0, 5, side=side, fps=24, duration=6)
                self.assertGreater(data["planted_transition_pairs"], 5)
                self.assertLess(data["max_sliding_px_per_frame"], .3,
                                f"foot slide at scale {scale}: {data}")


class SceneInteractionAndCameraTests(unittest.TestCase):
    def test_clip_library_is_available_to_actual_shot_with_no_new_actor_code(self):
        original = json.loads(SCENE.read_text())
        modified = copy.deepcopy(original)
        modified["actors"]["DAN"]["actions"].append({
            "clip": "keyframed", "source": "conversational_nod", "start": 10,
            "end": 11, "blend": .1
        })
        modified["camera_animation"] = {
            "center_x": {"keys": [[0, 960], [7.5, 985], [15, 960]]},
            "zoom": {"keys": [[0, 1], [5, 1.05], [15, 1]]}
        }
        compiled = compile_scene(MANIFEST, modified)
        shot = compiled["shots"][0]
        self.assertEqual(shot["camera_animation"], modified["camera_animation"])
        self.assertEqual(shot["actors"]["DAN"]["actions"][-1]["source"],
                         "conversational_nod")
        self.assertEqual(shot["dialogue"],
                         next(s["dialogue"] for s in json.loads(MANIFEST.read_text())["shots"] if s["id"]=="SHOT_001"))
        frame = render_frame(compiled, "SHOT_001", 10.5, size=(480, 270))
        self.assertEqual(frame.size, (480, 270))

    def test_camera_animation_is_deterministic_and_rejects_invalid_tracks(self):
        preset = {"center": [960, 540], "zoom": 1, "angle": 0}
        keys = {"center_x": {"keys": [[0, 960], [10, 1080]]},
                "zoom": {"keys": [[0, 1], [10, 1.2]]}}
        self.assertEqual(sample_camera(preset, keys, 5, 10),
                         sample_camera(preset, keys, 5, 10))
        self.assertAlmostEqual(sample_camera(preset, keys, 5, 10)["center"][0], 1020)
        self.assertAlmostEqual(sample_camera(preset, keys, 5, 10)["zoom"], 1.1)
        self.assertEqual(preset["center"], [960, 540])
        for invalid in [
            {"zoom": {"keys": [[0, 1], [1, 0]]}},
            {"center_x": {"keys": [[1, 0], [0, 8]]}},
            {"angle": {"keys": [[0, 60]]}},
            {"yaw": {"keys": [[0, 0]]}},
        ]:
            with self.assertRaises(ValueError):
                validate_camera_tracks(invalid, 10)

    def test_modern_interaction_draws_one_object_at_wrist_and_release(self):
        placement = {"position": [300, 310], "scale": .6,
                     "actions": [{"clip": "reach", "hand": "right",
                                  "start": 0, "end": 2,
                                  "target": [355, 225], "hold_last": True}]}
        object_data = {"id": "red_box", "shape": "rectangle", "size": [28, 28],
                       "color": "#FF0000", "position": [450, 365], "depth": 200,
                       "interaction": {"actor": "DAN", "hand": "right",
                                       "attach_at": .25, "release_at": 2.25,
                                       "landing": [355, 225]}}
        doc = {"canvas": [640, 480], "characters": {"DAN": {}},
               "shots": [{"id": "TEST", "duration": 4, "cast": ["DAN"],
                          "actors": {"DAN": placement},
                          "camera": {"zoom": 1, "center": [320, 240]},
                          "props": [object_data]}]}
        before = render_frame(doc, "TEST", 0, size=(640, 480))
        during = render_frame(doc, "TEST", 1.75, size=(640, 480))
        after = render_frame(doc, "TEST", 2.5, size=(640, 480))
        self.assertEqual(before.getpixel((450, 365)), (255, 0, 0))
        self.assertNotEqual(during.getpixel((450, 365)), (255, 0, 0))
        self.assertEqual(after.getpixel((355, 225)), (255, 0, 0))
        self.assertNotEqual(after.getpixel((450, 365)), (255, 0, 0))
        actor = Actor("DAN", placement=placement, objects={"red_box": object_data})
        contact = hand_prop_release_error(actor, object_data["interaction"], 4)
        self.assertTrue(math.isfinite(contact))

    def test_json_prop_release_prevents_jump_and_has_no_artwork_fallback(self):
        compiled = compile_scene(MANIFEST, SCENE)
        props = {item["id"]: item for item in compiled["shots"][0]["props"]}
        for item_id in ("recipe_card", "blue_bowl"):
            item = props[item_id]
            name = item["interaction"]["actor"]
            actor = Actor(name, placement=compiled["shots"][0]["actors"][name], objects=props)
            self.assertLessEqual(hand_prop_release_error(actor, item["interaction"], 15),
                                 item["interaction"].get("contact_tolerance", 24)+1e-4)
        from animation2d.episode03.engine import production_readiness
        self.assertEqual(len(production_readiness(compiled, "SHOT_001")), 3)


if __name__ == "__main__":
    unittest.main()
