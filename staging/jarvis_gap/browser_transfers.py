"""Proposal-only browser/file transfer contracts.

No browser is opened and no file is uploaded or downloaded here. These objects
bind a future review/approval to an exact local upload artifact or to an exact
download destination and byte ceiling.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024
MAX_FILENAME_CHARS = 180


def _resolved(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def _inside(path: Path, roots: tuple[Path, ...]) -> bool:
    return any(path == root or root in path.parents for root in roots)


def _safe_filename(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("filename is required")
    value = name.strip()
    if len(value) > MAX_FILENAME_CHARS:
        raise ValueError("filename is too long")
    if (Path(value).name != value or value in {".", ".."}
            or any(char in value for char in "\x00\r\n/\\")):
        raise ValueError("filename must be a simple basename")
    return value


def _hash_file(path: Path, *, max_bytes: int) -> tuple[str, int]:
    size = path.stat().st_size
    if size < 0 or size > max_bytes:
        raise ValueError("file exceeds transfer ceiling")
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            read += len(chunk)
            if read > max_bytes:
                raise ValueError("file exceeds transfer ceiling")
            digest.update(chunk)
    if read != size:
        raise RuntimeError("file changed while being hashed")
    return digest.hexdigest(), size


@dataclass(frozen=True)
class UploadProposal:
    path: str
    filename: str
    size_bytes: int
    sha256: str

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "local_path_disclosure": False,
            "execution_authority": False,
        }


def propose_upload(path: str | Path, *, allowed_roots: list[str | Path],
                   max_bytes: int = MAX_UPLOAD_BYTES) -> UploadProposal:
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_UPLOAD_BYTES:
        raise ValueError("max_bytes invalid")
    roots = tuple(_resolved(root) for root in allowed_roots)
    if not roots:
        raise ValueError("allowed root required")
    candidate = _resolved(path)
    if not _inside(candidate, roots):
        raise PermissionError("upload path outside allowed roots")
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("upload path must be a regular file")
    digest, size = _hash_file(candidate, max_bytes=max_bytes)
    return UploadProposal(str(candidate), candidate.name, size, digest)


@dataclass(frozen=True)
class DownloadProposal:
    directory: str
    filename: str
    max_bytes: int
    expected_origin: str

    @property
    def destination(self) -> str:
        return str(Path(self.directory) / self.filename)

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "max_bytes": self.max_bytes,
            "expected_origin": self.expected_origin,
            "destination_path_disclosure": False,
            "execution_authority": False,
        }


def propose_download(directory: str | Path, filename: str, *,
                     allowed_roots: list[str | Path], max_bytes: int,
                     expected_origin: str, overwrite: bool = False) -> DownloadProposal:
    if overwrite:
        raise PermissionError("overwrite is never permitted")
    if isinstance(max_bytes, bool) or not isinstance(max_bytes, int) or not 1 <= max_bytes <= MAX_DOWNLOAD_BYTES:
        raise ValueError("max_bytes invalid")
    if not isinstance(expected_origin, str) or not expected_origin.startswith(("https://", "http://")):
        raise ValueError("expected_origin invalid")
    roots = tuple(_resolved(root) for root in allowed_roots)
    if not roots:
        raise ValueError("allowed root required")
    destination_dir = _resolved(directory)
    if not _inside(destination_dir, roots):
        raise PermissionError("download directory outside allowed roots")
    name = _safe_filename(filename)
    destination = destination_dir / name
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("download destination already exists")
    return DownloadProposal(str(destination_dir), name, max_bytes, expected_origin)
