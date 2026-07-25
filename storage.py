import os
import re
from pathlib import Path
from typing import Protocol

import config


class PrivateFileStorage(Protocol):
    def save(self, filename: str, content: bytes) -> str:
        ...

    def resolve(self, reference: str) -> Path:
        ...


class LocalPrivateStorage:
    """Development storage with traversal-safe paths.

    Production can replace this adapter with S3/R2-compatible private object
    storage without changing upload or authorization routes.
    """

    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_name(self, filename: str) -> str:
        base = Path(filename or "upload.pdf").name
        cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
        return cleaned[:180] or "upload.pdf"

    def save(self, filename: str, content: bytes) -> str:
        target = (self.root / self._safe_name(filename)).resolve()
        if self.root not in target.parents:
            raise ValueError("Unsafe storage path")
        target.write_bytes(content)
        os.chmod(target, 0o600)
        return str(target)

    def resolve(self, reference: str) -> Path:
        target = Path(reference).resolve()
        if self.root not in target.parents or not target.is_file():
            raise FileNotFoundError("Private file was not found.")
        return target


private_storage: PrivateFileStorage = LocalPrivateStorage(config.UPLOAD_DIR)
