"""Safety and single-shot parity tests; do not depend on unpublished production art."""
import json
from pathlib import Path
import tempfile
import unittest

from benchmark.shot001.common import (
    CAST, DURATION, FPS, LINES, MANIFEST, SHOT, inputs, load_contract,
)
from benchmark.shot001.compare import compare
from benchmark.shot001.render import render as production_render


class Episode03FairComparisonTests(unittest.TestCase):
    def test_both_engines_locked_to_same_source_screenplay(self):
        before = MANIFEST.read_bytes()
        data, shot = load_contract()
        self.assertEqual(tuple(shot["cast"]), CAST)
        self.assertEqual(tuple((d["speaker"], d["text"]) for d in shot["dialogue"]), LINES)
        self.assertEqual((FPS, DURATION), (24, 15))
        self.assertEqual(data["canvas"], [1920, 1080])
        self.assertEqual(before, MANIFEST.read_bytes(), "Benchmark must not rewrite source manifest")

    def test_shared_contact_choreography_is_reachable(self):
        _, shot = load_contract()
        self.assertEqual(shot["actors"]["MAYA"]["action"]["end"], 2.0)
        self.assertEqual(shot["actors"]["NINA"]["action"]["hand"], "left")
        self.assertEqual(shot["actors"]["NINA"]["action"]["end"], 2.5)
        self.assertEqual(shot["actors"]["NINA"]["position"], [1250, 650])
        self.assertEqual(shot["camera"]["center"], [960, 540])
        self.assertEqual(shot["camera"]["zoom"], 1)
        self.assertEqual({p["id"] for p in shot["props"]} >=
                         {"recipe_card", "recipe_stand", "blue_bowl"}, True)

    def test_missing_cast_art_must_block_real_benchmark(self):
        data, _ = load_contract()
        paths = [Path(data["__base_dir__"]) / data["characters"][a]["rig"] for a in CAST]
        if all(p.exists() for p in paths):
            self.skipTest("production rigs are now present: visual readiness needs review")
        with self.assertRaisesRegex(RuntimeError, "PRODUCTION BENCHMARK BLOCKED"):
            inputs(Path("build/shot001/unprovided"), require_audio=False)

    def test_pair_verifier_rejects_different_inputs(self):
        with tempfile.TemporaryDirectory() as temp:
            a = Path(temp) / "a"
            b = Path(temp) / "b"
            a.mkdir()
            b.mkdir()
            (a / "benchmark.json").write_text(json.dumps({
                "version": "python", "source_input": {"audio": "one"},
                "encoder": {"fps": 24}, "media_validation": {"frames": 360}
            }))
            (b / "benchmark.json").write_text(json.dumps({
                "version": "rigby", "source_input": {"audio": "two"},
                "encoder": {"fps": 24}, "media_validation": {"frames": 360}
            }))
            with self.assertRaisesRegex(AssertionError, "Art, narration"):
                compare(a, b, Path(temp) / "report")


if __name__ == "__main__":
    unittest.main()
