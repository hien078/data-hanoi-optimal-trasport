"""Download and unpack source datasets.

Only downloads when the target file does not already exist.
Never claims success unless the file exists on disk afterwards.
"""

from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import data_dir, get_logger, load_config

log = get_logger("download")

# HDX rejects requests without a User-Agent (HTTP 202/403).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(hanoi-ot research data pipeline; university project)"
)


class DownloadError(RuntimeError):
    """Raised when a download fails or the file is missing afterwards."""


def sha256(path: Path, chunk: int = 1 << 20) -> str:
    """Return the hex SHA-256 checksum of a file.

    Args:
        path: File to hash.
        chunk: Read chunk size in bytes.

    Returns:
        Hex digest string.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def download_file(url: str, dest: Path, force: bool = False) -> Path:
    """Download ``url`` to ``dest`` (skip if present unless ``force``).

    Args:
        url: Source URL.
        dest: Destination file path.
        force: Re-download even if the file exists.

    Returns:
        Path to the downloaded file.

    Raises:
        DownloadError: On network failure or if the file is absent afterwards.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not force:
        log.info("Skip download (exists): %s", dest.name)
        return dest
    log.info("Downloading %s -> %s", url, dest)
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=300) as resp, dest.open("wb") as out:
            shutil.copyfileobj(resp, out, length=1 << 20)
    except (HTTPError, URLError, OSError) as e:
        # Remove partial file so we never treat a truncated download as done.
        dest.unlink(missing_ok=True)
        raise DownloadError(f"Download failed: {url}: {e}") from e
    if not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise DownloadError(f"Download produced no file: {url}")
    log.info("Done: %s (%.1f MB)", dest.name, dest.stat().st_size / 1e6)
    return dest


def unzip(archive: Path, dest_dir: Path, overwrite: bool = False) -> list[Path]:
    """Extract a zip archive into ``dest_dir``; return extracted paths.

    Args:
        archive: Zip file to extract.
        dest_dir: Target directory (created if missing).
        overwrite: Re-extract even if files exist.

    Returns:
        List of extracted file paths.

    Raises:
        DownloadError: If the archive is invalid or empty.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            if not names:
                raise DownloadError(f"Empty archive: {archive}")
            marker = dest_dir / ".extracted"
            if marker.exists() and not overwrite:
                log.info("Skip unzip (already extracted): %s", archive.name)
                return sorted(
                    p for p in dest_dir.rglob("*") if p.is_file() and p != marker
                )
            zf.extractall(dest_dir)
            marker.touch()
    except zipfile.BadZipFile as e:
        raise DownloadError(f"Invalid zip archive: {archive}: {e}") from e
    extracted = sorted(p for p in dest_dir.rglob("*") if p.is_file() and p != marker)
    log.info("Extracted %d files from %s", len(extracted), archive.name)
    return extracted


def download_source(source_key: str, force: bool = False) -> Path:
    """Download + unzip one configured source into ``data/raw/<key>/``.

    Args:
        source_key: Key under ``sources`` in config (e.g. ``admin_boundaries``).
        force: Re-download even if present.

    Returns:
        Path to the raw download directory containing extracted files.

    Raises:
        DownloadError: On failure (never silently).
        KeyError: If the source key is not configured.
    """
    cfg = load_config()
    src: dict[str, Any] = cfg["sources"][source_key]
    raw_dir = data_dir("raw") / source_key
    archive = raw_dir / src["file"]
    download_file(src["url"], archive, force=force)
    files = unzip(archive, raw_dir / "extracted")
    if not files:
        raise DownloadError(f"No files extracted for source '{source_key}'")
    return raw_dir / "extracted"
