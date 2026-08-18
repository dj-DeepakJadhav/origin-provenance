"""Filesystem document store. No AWS, no credentials, no network."""

from __future__ import annotations

import re
from pathlib import Path

from .base import DocumentStore

# Document keys become path segments, so they are constrained rather than
# sanitised. A key that could escape the root is a bug in the caller, and
# quietly rewriting it would hide that.
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")


def _validate(key: str) -> str:
    if not _SAFE_KEY.match(key or ""):
        raise ValueError(
            f"unsafe document key {key!r}: expected alphanumerics, dot, dash, "
            "underscore and forward slash, not starting with a separator"
        )
    if ".." in key.split("/"):
        raise ValueError(f"document key {key!r} attempts to traverse upward")
    return key


class LocalDocumentStore(DocumentStore):
    name = "local"

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        candidate = (self._root / _validate(key)).resolve()
        # Defence in depth: even with a validated key, confirm the resolved path
        # is inside the root before writing to it.
        if not candidate.is_relative_to(self._root):
            raise ValueError(f"document key {key!r} resolves outside the store root")
        return candidate

    def put(self, key: str, data: bytes) -> str:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash mid-write cannot leave a truncated
        # document that would later hash differently than it was recorded.
        temp = path.with_suffix(path.suffix + ".partial")
        temp.write_bytes(data)
        temp.replace(path)
        return self.uri(key)

    def get(self, key: str) -> bytes:
        path = self._path(key)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise KeyError(key) from exc

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def uri(self, key: str) -> str:
        return self._path(key).as_uri()
