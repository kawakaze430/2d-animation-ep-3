"""Offline provider contract acceptance: no model downloads or paid services.

Mock/fixture only. The real rembg model and its particular weight license are
not bundled, downloaded or exercised by CI.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import tempfile
import time
import unittest

from PIL import Image, ImageDraw

from animfactory import Project
from animfactory.providers import (
    OfflineThresholdFixture, ProviderDescriptor, ProviderDisabled, ProviderRegistry,
    RembgPreloadedSession, import_prepared,
)


def make_source(*, white=True):
    image = Image.new("RGB", (36, 28), (255, 255, 255) if white else (90, 80, 100))
    ImageDraw.Draw(image).ellipse((7, 4, 29, 24), fill="#8f70ac")
    file = BytesIO()
    image.save(file, "PNG")
    return file.getvalue()


def make_output():
    image = Image.new("RGBA", (36, 28), (255, 255, 255, 0))
    ImageDraw.Draw(image).ellipse((7, 4, 29, 24), fill="#8f70ac")
    file = BytesIO()
    image.save(file, "PNG")
    return file.getvalue()


class StubProvider:
    def __init__(self, *, network=False, billable=False, result=None, sleep=0):
        self.descriptor = ProviderDescriptor(
            id="mock_service", version="0.1", capabilities=("background_removal",),
            requires_network=network, billable=billable
        )
        self.output = result if result is not None else make_output()
        self.calls = 0
        self.sleep = sleep

    def process(self, raw):
        self.calls += 1
        if self.sleep:
            time.sleep(self.sleep)
        return self.output


class ProviderContractTests(unittest.TestCase):
    def test_default_disabled_never_invokes_provider(self):
        registry = ProviderRegistry()
        adapter = StubProvider()
        registry.register(adapter)
        self.assertFalse(registry.list()[0]["enabled"])
        with self.assertRaises(ProviderDisabled):
            registry.prepare("mock_service", make_source())
        with self.assertRaises(ProviderDisabled):
            registry.enable("mock_service")
        self.assertEqual(adapter.calls, 0)
        registry.enable("mock_service", approved=True)
        self.assertEqual(registry.prepare("mock_service", make_source()).provider.id, "mock_service")
        self.assertEqual(adapter.calls, 1)
        registry.disable("mock_service")
        with self.assertRaises(ProviderDisabled):
            registry.prepare("mock_service", make_source())
        self.assertEqual(adapter.calls, 1)

    def test_offline_fixture_is_deterministic_and_artifact_persists_with_provenance(self):
        registry = ProviderRegistry()
        registry.register(OfflineThresholdFixture())
        registry.enable("offline_fixture", approved=True)
        raw = make_source()
        first = registry.prepare("offline_fixture", raw)
        second = registry.prepare("offline_fixture", raw)
        self.assertEqual(first.png, second.png)
        self.assertEqual(first.output_sha256, second.output_sha256)
        self.assertEqual(first.input_sha256, second.input_sha256)
        self.assertIn("original_sha256", first.provenance())
        with Image.open(BytesIO(first.png)) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)
            self.assertEqual(image.getpixel((18, 14))[3], 255)
        with tempfile.TemporaryDirectory() as work:
            project = Project.create(Path(work) / "film", "offline_provider", "Offline provider demo",
                                     canvas=(160, 90), fps=12)
            aid = import_prepared(project, first, "foreground", license_label="original-art")
            self.assertEqual(aid, "foreground")
            self.assertEqual(project.doc["assets"][aid]["sha256"], first.output_sha256)
            self.assertIn(first.input_sha256, project.doc["assets"][aid]["source"])
            self.assertEqual(project.doc["assets"][aid]["license"], "original-art")
            self.assertTrue(Project.open(project.root).verify_assets())

    def test_invalid_images_fail_before_or_after_provider_execution(self):
        registry = ProviderRegistry()
        adapter = StubProvider()
        registry.register(adapter)
        registry.enable("mock_service", approved=True)
        for raw in (b"", b"not an image", b"\x00" * 500):
            with self.subTest(raw=raw[:12]), self.assertRaises(ValueError):
                registry.prepare("mock_service", raw)
        self.assertEqual(adapter.calls, 0)
        for output in (b"bad bytes", make_source()):
            adapter.output = output
            with self.assertRaises(ValueError):
                registry.prepare("mock_service", make_source())
        self.assertEqual(adapter.calls, 2)

    def test_network_and_billable_require_separate_per_operation_approval(self):
        registry = ProviderRegistry()
        adapter = StubProvider(network=True, billable=True)
        registry.register(adapter)
        registry.enable("mock_service", approved=True)
        with self.assertRaises(ProviderDisabled):
            registry.prepare("mock_service", make_source())
        with self.assertRaises(ProviderDisabled):
            registry.prepare("mock_service", make_source(), approve_network=True)
        self.assertEqual(adapter.calls, 0)
        result = registry.prepare("mock_service", make_source(),
                                  approve_network=True, approve_billable=True)
        self.assertEqual(result.provider.billable, True)
        self.assertEqual(adapter.calls, 1)

    def test_bad_capability_timeout_duplicate_registration_and_disabled_behavior(self):
        registry = ProviderRegistry()
        adapter = StubProvider(sleep=.015)
        registry.register(adapter)
        with self.assertRaises(FileExistsError):
            registry.register(adapter)
        with self.assertRaises(KeyError):
            registry.enable("not-registered", approved=True)
        registry.enable("mock_service", approved=True)
        with self.assertRaises(ValueError):
            registry.prepare("mock_service", make_source(), capability="rendering")
        with self.assertRaises(ValueError):
            registry.prepare("mock_service", make_source(), timeout_s=-1)
        with self.assertRaises(TimeoutError):
            registry.prepare("mock_service", make_source(), timeout_s=.001)
        self.assertEqual(adapter.calls, 1)

    def test_rembg_adapter_uses_only_preloaded_session_and_mocked_remove(self):
        marker = object()
        calls = []
        def fake_remove(raw, *, session):
            calls.append((raw, session))
            return make_output()
        adapter = RembgPreloadedSession(
            marker, model="u2netp", model_sha256="a" * 64,
            model_license="artist-reviewed-model-terms", version="2.0.67",
            remove_function=fake_remove,
        )
        registry = ProviderRegistry()
        registry.register(adapter)
        registry.enable("rembg_local", approved=True)
        result = registry.prepare("rembg_local", make_source())
        self.assertEqual(len(calls), 1)
        self.assertIs(calls[0][1], marker)
        self.assertEqual(result.provider.model_id, "u2netp")
        self.assertEqual(result.provenance()["model_sha256"], "a" * 64)
        with self.assertRaises(ProviderDisabled):
            RembgPreloadedSession(marker, model="atlascloud", model_sha256="a" * 64,
                                  model_license="reviewed", version="1")
        with self.assertRaises(ProviderDisabled):
            RembgPreloadedSession(marker, model="u2netp", model_sha256="a" * 64,
                                  model_license="unspecified", version="1")
        with self.assertRaises(ValueError):
            RembgPreloadedSession(None, model="u2netp", model_sha256="a" * 64,
                                  model_license="reviewed", version="1")

    def test_provenance_and_provider_rights_are_explicit(self):
        with self.assertRaises(ValueError):
            ProviderDescriptor("bad provider", "1", ("background_removal",), False, False)
        with self.assertRaises(ValueError):
            ProviderDescriptor("fixture_good", "1", ("background_removal",),
                               False, False, model_sha256="UNKNOWN")
        registry = ProviderRegistry()
        registry.register(OfflineThresholdFixture())
        registry.enable("offline_fixture", approved=True)
        with tempfile.TemporaryDirectory() as temp:
            project = Project.create(Path(temp)/"p", "provider_art", "Provenance test")
            result = registry.prepare("offline_fixture", make_source())
            with self.assertRaises(ValueError):
                import_prepared(project, result, "test", license_label="")
            self.assertFalse(project.doc["assets"])


if __name__ == "__main__":
    unittest.main()
