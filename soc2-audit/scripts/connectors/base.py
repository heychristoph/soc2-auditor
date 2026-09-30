"""BundleWriter: the only way connectors write to bundle/.

It owns file layout, artifact IDs, hashing and the manifest, so every connector
produces the same shape and the audit steps never need to know the source.
"""

from __future__ import annotations

import json
import mimetypes
import re
import shutil
import urllib.error
import urllib.request
from pathlib import Path

from core import dump_json, dump_yaml, now_utc, schema_errors, sha256_file, write_csv, AuditError

CONTROL_COLUMNS = ["id", "title", "description", "criteria", "owner", "frequency", "nature", "population", "source_ref"]

# Matches criterion IDs such as CC6.1, A1.2, C1.1, PI1.3, P6.7 inside free text.
CRITERION_RE = re.compile(r"\b(CC[1-9]\.[0-9]|A1\.[1-3]|C1\.[12]|PI1\.[1-5]|P[1-8]\.[1-7])\b")


def find_criteria(*texts) -> list[str]:
    found = []
    for text in texts:
        if not text:
            continue
        text = text if isinstance(text, str) else json.dumps(text)
        for match in CRITERION_RE.findall(text):
            if match not in found:
                found.append(match)
    return found


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


class BundleWriter:
    def __init__(self, bundle_dir: Path, connector: str, source: str = ""):
        self.dir = bundle_dir
        self.connector = connector
        self.source = source
        self.artifacts: list[dict] = []
        self.warnings: list[str] = []
        self._next_ev = 1
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- helpers for connectors ---

    def warn(self, message: str) -> None:
        """Record something the auditor should know about the pull (missing data, API errors)."""
        print(f"warning: {message}")
        self.warnings.append(message)

    @staticmethod
    def http_json(url: str, *, method: str = "GET", headers: dict | None = None, body=None, timeout: int = 60):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={"Accept": "application/json", **(headers or {})})
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None, dict(resp.headers)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:500]
            raise AuditError(f"{method} {url} failed with HTTP {e.code}: {detail}") from e

    @staticmethod
    def http_download(url: str, dest: Path, *, headers: dict | None = None, timeout: int = 120) -> None:
        req = urllib.request.Request(url, headers=headers or {})
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as f:
                shutil.copyfileobj(resp, f)
        except urllib.error.HTTPError as e:
            raise AuditError(f"Download of {url} failed with HTTP {e.code}") from e

    # --- writing the bundle ---

    def set_controls(self, rows: list[dict]) -> None:
        """Write the control matrix. `criteria` may be a list or a space-separated string."""
        clean = []
        for row in rows:
            row = dict(row)
            if isinstance(row.get("criteria"), (list, tuple)):
                row["criteria"] = " ".join(row["criteria"])
            clean.append(row)
        path = self.dir / "controls.csv"
        write_csv(path, clean, CONTROL_COLUMNS)
        self._register(path, "SY-controls", kind="controls", title="Control matrix", obtained="client")

    def set_system(self, system: dict, *, obtained: str = "client") -> None:
        """Write management's system description inputs (see references/engagement-folder.md)."""
        path = self.dir / "system.yaml"
        dump_yaml(system, path)
        self._register(path, "SY-system", kind="system", title="System description inputs", obtained=obtained)

    def add_population(self, name: str, rows: list[dict], *, title: str, obtained: str = "direct", source_ref: str = "") -> str:
        """Write a population file. Each row needs `id` and `date`; other columns are kept."""
        for i, row in enumerate(rows):
            if not row.get("id") or not row.get("date"):
                raise AuditError(f"Population '{name}' row {i + 1} needs non-empty 'id' and 'date' columns.")
        artifact_id = f"PO-{slug(name)}"
        path = self.dir / "populations" / f"{slug(name)}.csv"
        extra = []
        for row in rows:
            extra += [k for k in row if k not in ("id", "date") and k not in extra]
        write_csv(path, rows, ["id", "date", *extra])
        self._register(path, artifact_id, kind="population", title=title, obtained=obtained, source_ref=source_ref, media_type="text/csv")
        return artifact_id

    def add_file(self, src: Path, *, title: str, kind: str = "evidence", controls=(), date: str | None = None,
                 obtained: str = "direct", source_ref: str = "", filename: str | None = None) -> str:
        """Copy a file into bundle/evidence/ and register it. Returns the artifact ID."""
        artifact_id = self._new_id()
        dest = self.dir / "evidence" / f"{artifact_id}_{filename or Path(src).name}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        self._register(dest, artifact_id, kind=kind, title=title, controls=controls, date=date, obtained=obtained, source_ref=source_ref)
        return artifact_id

    def add_bytes(self, content: bytes | str, filename: str, *, title: str, kind: str = "evidence", controls=(),
                  date: str | None = None, obtained: str = "direct", source_ref: str = "") -> str:
        artifact_id = self._new_id()
        dest = self.dir / "evidence" / f"{artifact_id}_{filename}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content.encode() if isinstance(content, str) else content)
        self._register(dest, artifact_id, kind=kind, title=title, controls=controls, date=date, obtained=obtained, source_ref=source_ref)
        return artifact_id

    def add_download(self, url: str, filename: str, *, title: str, headers: dict | None = None, **meta) -> str | None:
        """Download a file into the bundle. On failure, records a warning and returns None."""
        artifact_id = self._new_id()
        dest = self.dir / "evidence" / f"{artifact_id}_{filename}"
        try:
            self.http_download(url, dest, headers=headers)
        except AuditError as e:
            self.warn(f"could not download '{title}': {e}")
            return None
        self._register(dest, artifact_id, title=title, **{"kind": "evidence", **meta})
        return artifact_id

    def finish(self) -> dict:
        manifest = {
            "schema_version": 1,
            "connector": self.connector,
            "source": self.source,
            "collected_at": now_utc(),
            "warnings": self.warnings,
            "artifacts": self.artifacts,
        }
        errors = schema_errors(manifest, "manifest")
        if errors:
            raise AuditError("Connector produced an invalid manifest:\n  " + "\n  ".join(errors[:20]))
        dump_json(manifest, self.dir / "manifest.json")
        return manifest

    # --- internals ---

    def _new_id(self) -> str:
        artifact_id = f"EV-{self._next_ev:04d}"
        self._next_ev += 1
        return artifact_id

    def _register(self, path: Path, artifact_id: str, *, kind: str, title: str, controls=(), date=None,
                  obtained: str = "direct", source_ref: str = "", media_type: str | None = None) -> None:
        if any(a["id"] == artifact_id for a in self.artifacts):
            raise AuditError(f"Duplicate artifact ID {artifact_id}; population names must be unique.")
        entry = {
            "id": artifact_id,
            "path": path.relative_to(self.dir).as_posix(),
            "sha256": sha256_file(path),
            "bytes": path.stat().st_size,
            "kind": kind,
            "title": title,
            "media_type": media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "controls": sorted(set(controls)),
            "obtained": obtained,
        }
        if date:
            entry["date"] = str(date)[:10]
        if source_ref:
            entry["source_ref"] = source_ref
        self.artifacts.append(entry)
