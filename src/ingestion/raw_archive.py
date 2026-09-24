"""Immutable raw archive: every response is written once, with a checksum manifest."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from src.api.models import RawPage


def _extension(content_type: str) -> str:
    ct = content_type.lower()
    if "json" in ct:
        return "json"
    if "html" in ct:
        return "html"
    return "txt"


class RawArchive:
    def __init__(self, root: Path):
        self.root = root

    def run_dir(self, source: str, run_id: str) -> Path:
        return self.root / source / run_id

    def write(self, run_id: str, page: RawPage) -> Path:
        run_dir = self.run_dir(page.source, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        data = page.content.encode("utf-8")
        path = run_dir / f"page_{page.page_index:05d}.{_extension(page.content_type)}"
        # "xb" = exclusive create: an archived response can never be overwritten.
        with open(path, "xb") as fh:
            fh.write(data)
        entry = {
            "run_id": run_id,
            "source": page.source,
            "page_index": page.page_index,
            "file": path.name,
            "url": page.url,
            "request_params": page.request_params,
            "status_code": page.status_code,
            "content_type": page.content_type,
            "retrieved_at": page.retrieved_at.isoformat(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        with open(run_dir / "manifest.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return path

    def read_pages(self, source: str, run_id: str) -> list[RawPage]:
        """Rebuild the raw pages of one run from its manifest, for offline re-parsing.

        Raises FileNotFoundError if the run directory or its manifest is absent.
        """
        run_dir = self.run_dir(source, run_id)
        manifest_path = run_dir / "manifest.jsonl"
        pages = []
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            content = (run_dir / entry["file"]).read_text(encoding="utf-8")
            pages.append(RawPage(
                source=entry["source"],
                page_index=entry["page_index"],
                url=entry["url"],
                request_params=entry["request_params"],
                status_code=entry["status_code"],
                content=content,
                content_type=entry["content_type"],
                retrieved_at=datetime.fromisoformat(entry["retrieved_at"]),
            ))
        return pages

    def verify(self, source: str, run_id: str) -> list[str]:
        """Return files whose checksum no longer matches the manifest."""
        run_dir = self.run_dir(source, run_id)
        bad = []
        for line in (run_dir / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
            entry = json.loads(line)
            data = (run_dir / entry["file"]).read_bytes()
            if hashlib.sha256(data).hexdigest() != entry["sha256"]:
                bad.append(entry["file"])
        return bad
