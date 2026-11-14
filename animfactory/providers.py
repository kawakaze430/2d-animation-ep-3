"""Opt-in, offline-by-default provider contracts for asset preparation.

NO plugin/module autodiscovery, arbitrary Python eval, secret access, server
requests, model downloads, paid APIs, GPU jobs or product schema changes.
Only an explicitly registered and enabled adapter can process an IMAGE BUFFER.
An artist always remains responsible for layer roles and hidden anatomy.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
from math import isfinite
from pathlib import Path
import re
import tempfile
import time
from typing import Protocol

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 16_777_216
SHA = re.compile(r"^[0-9a-f]{64}$")


class ProviderDisabled(PermissionError):
    pass


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    version: str
    capabilities: tuple[str, ...]
    requires_network: bool
    billable: bool
    model_id: str = "none"
    model_sha256: str = "none"
    model_license: str = "not-applicable"

    def __post_init__(self):
        if (not re.fullmatch(r"[a-z][a-z0-9_-]{1,63}", self.id)
                or not isinstance(self.version, str) or not self.version
                or not self.capabilities
                or not all(isinstance(x,str) and x for x in self.capabilities)):
            raise ValueError("Provider descriptor needs safe ID, version and capabilities")
        if type(self.requires_network) is not bool or type(self.billable) is not bool:
            raise ValueError("Provider permission flags must be boolean")
        if self.model_sha256 != "none" and not SHA.fullmatch(self.model_sha256):
            raise ValueError("Model provenance requires a lowercase SHA-256")


class ImageAdapter(Protocol):
    descriptor: ProviderDescriptor
    def process(self, png_or_jpeg: bytes) -> bytes: ...


@dataclass(frozen=True)
class PreparedImage:
    png: bytes
    provider: ProviderDescriptor
    input_sha256: str
    output_sha256: str
    elapsed_s: float

    def provenance(self) -> dict:
        return {
            "provider": self.provider.id,
            "version": self.provider.version,
            "model": self.provider.model_id,
            "model_sha256": self.provider.model_sha256,
            "model_license": self.provider.model_license,
            "original_sha256": self.input_sha256,
            "result_sha256": self.output_sha256,
            "elapsed_s": round(self.elapsed_s, 6),
        }


def _validate_source(raw: bytes):
    if not isinstance(raw,bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError("Provider image must be a bounded byte array")
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format not in ("PNG","JPEG") or image.width*image.height>MAX_PIXELS:
                raise ValueError("Provider input requires reasonable PNG or JPEG")
            image.load()
            return image.convert("RGBA")
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as e:
        raise ValueError("Invalid provider source image") from e


def _validate_output(raw):
    if not isinstance(raw,bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise ValueError("Provider output requires bounded PNG bytes")
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format!="PNG" or "A" not in image.getbands():
                raise ValueError("Provider output must be transparent-capable PNG")
            if image.width*image.height>MAX_PIXELS:
                raise ValueError("Provider output pixel count exceeds limit")
            lo,hi=image.getchannel("A").getextrema()
            if lo==255 or hi==0:
                raise ValueError("Provider output must contain both visible and transparent pixels")
            image.load()
    except (OSError,UnidentifiedImageError,Image.DecompressionBombError) as e:
        raise ValueError("Invalid provider PNG output") from e


class ProviderRegistry:
    """Registration is inert. User explicitly enables a named adapter before use."""

    def __init__(self):
        self._registered = {}
        self._enabled = set()

    def register(self, adapter: ImageAdapter):
        descriptor = adapter.descriptor
        if descriptor.id in self._registered:
            raise FileExistsError("Provider already registered")
        self._registered[descriptor.id] = adapter

    def list(self):
        return [{"id":d.id,"version":d.version,
                 "capabilities":list(d.capabilities),
                 "requires_network":d.requires_network,
                 "billable":d.billable,
                 "enabled":d.id in self._enabled}
                for a in self._registered.values() for d in [a.descriptor]]

    def enable(self, provider_id, *, approved=False):
        if provider_id not in self._registered:
            raise KeyError("Unknown provider")
        if approved is not True:
            raise ProviderDisabled("Provider enabling requires an explicit user approval")
        self._enabled.add(provider_id)

    def disable(self, provider_id):
        self._enabled.discard(provider_id)

    def prepare(self, provider_id: str, raw: bytes, *, capability="background_removal",
                approve_network=False, approve_billable=False, timeout_s=30):
        if provider_id not in self._registered:
            raise KeyError("Unknown provider")
        if provider_id not in self._enabled:
            raise ProviderDisabled("Provider disabled; normal editing stays offline")
        adapter = self._registered[provider_id]
        d = adapter.descriptor
        if capability not in d.capabilities:
            raise ValueError("Provider does not support requested capability")
        if d.requires_network and approve_network is not True:
            raise ProviderDisabled("Network provider needs separate per-operation approval")
        if d.billable and approve_billable is not True:
            raise ProviderDisabled("Billable provider needs separate per-operation approval")
        if type(timeout_s) not in (int,float) or not isfinite(timeout_s) or not 0<timeout_s<=3600:
            raise ValueError("Timeout budget invalid")
        _validate_source(raw)
        start=time.perf_counter()
        result=adapter.process(raw)
        elapsed=time.perf_counter()-start
        # This clock check does not forcibly kill a blocking third-party
        # inference call. Hosted inference must use a cancellable worker.
        if elapsed>timeout_s:
            raise TimeoutError("Provider exceeded local execution budget")
        _validate_output(result)
        return PreparedImage(result,d,hashlib.sha256(raw).hexdigest(),
                             hashlib.sha256(result).hexdigest(),elapsed)


class OfflineThresholdFixture:
    """Deterministic test/preprocessing adapter; NOT model-based segmentation."""

    descriptor = ProviderDescriptor(
        id="offline_fixture", version="1.0", capabilities=("background_removal",),
        requires_network=False, billable=False
    )

    def process(self, raw):
        image=_validate_source(raw)
        pixels=image.load()
        for y in range(image.height):
            for x in range(image.width):
                r,g,b,a=pixels[x,y]
                if min(r,g,b)>=245:
                    pixels[x,y]=(r,g,b,0)
        buffer=BytesIO()
        image.save(buffer,format="PNG")
        return buffer.getvalue()


class RembgPreloadedSession:
    """Optional real rembg SDK adapter; explicit preloaded LOCAL model only.

    Important: this class never calls rembg.new_session(), which may download
    model weights. The user must supply a previously created local session,
    approved exact model hash, rights and offline intent. Do not use cloud
    rembg model backends; no bundled weights, downloads or network services.
    """

    LOCAL_MODELS=frozenset((
        "u2net","u2netp","u2net_human_seg","u2net_cloth_seg",
        "isnet-general-use","isnet-anime","silueta"
    ))

    def __init__(self, session, *, model, model_sha256, model_license,
                 version, remove_function=None):
        if session is None:
            raise ValueError("Pass an existing local rembg model session; auto-download forbidden")
        if model not in self.LOCAL_MODELS:
            raise ProviderDisabled("Cloud/unknown rembg models are forbidden")
        if not isinstance(model_license,str) or model_license in ("","unknown","unspecified"):
            raise ProviderDisabled("Model rights must be inspected and recorded")
        self.descriptor=ProviderDescriptor(
            id="rembg_local",version=version,
            capabilities=("background_removal",),
            requires_network=False,billable=False,
            model_id=model,model_sha256=model_sha256,
            model_license=model_license)
        self.session=session
        self._remove=remove_function

    def process(self, raw):
        _validate_source(raw)
        if self._remove is not None:
            removal=self._remove
        else:
            try:
                from rembg import remove as removal  # optional dependency, ONLY when executed
            except ImportError as e:
                raise RuntimeError('Install rembg CPU in a separate opt-in environment') from e
        output=removal(raw,session=self.session)
        if not isinstance(output,bytes):
            raise ValueError("rembg must return output PNG bytes")
        return output


def import_prepared(project, artifact: PreparedImage, asset_id, *, license_label):
    """Persist through the existing SHA256/provenance-checked asset importer."""
    if not isinstance(license_label,str) or not license_label.strip():
        raise ValueError("User must identify original/generated asset rights")
    label=(artifact.provider.id+":"+artifact.provider.version+
           ":"+artifact.provider.model_id+":"+artifact.provider.model_sha256+
           ":input="+artifact.input_sha256)
    with tempfile.TemporaryDirectory(prefix="animfactory-prepared-") as work:
        path=Path(work)/"prepared.png"
        path.write_bytes(artifact.png)
        return project.import_image(path,asset_id,kind="image",
                                    source_label=label,license_label=license_label)
