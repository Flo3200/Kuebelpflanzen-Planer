"""File storage behind an interface. Local folder now; an S3-compatible backend can be added
by implementing StorageBackend and selecting it with KP_STORAGE_BACKEND."""

from __future__ import annotations

import hashlib
import io
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps

from app.core.config import get_config


class StorageBackend(Protocol):
    def put(self, key: str, data: bytes, content_type: str) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class LocalStorage:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("invalid storage key")
        return path

    def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


@lru_cache
def get_storage() -> StorageBackend:
    cfg = get_config()
    if cfg.storage_backend == "local":
        return LocalStorage(cfg.files_path)
    raise RuntimeError(f"unknown storage backend {cfg.storage_backend!r}")


def new_key(tenant_id: uuid.UUID | None, purpose: str, ext: str) -> str:
    tenant = str(tenant_id) if tenant_id else "platform"
    fid = uuid.uuid4().hex
    return f"{tenant}/{purpose}/{fid[:2]}/{fid}{ext}"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}


def clean_image(data: bytes, max_side: int = 2400) -> tuple[bytes, int, int]:
    """Apply EXIF orientation, drop all metadata (incl. GPS) and limit the size. Returns JPEG."""
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        out = io.BytesIO()
        # a fresh image without info/exif is written
        clean = Image.new(img.mode, img.size)
        clean.paste(img)
        clean.save(out, format="JPEG", quality=86, optimize=True)
        return out.getvalue(), clean.width, clean.height
