"""Shared helpers: the engagement folder layout, file IO, hashing and schema checks.

Every other module goes through `Engagement` to find files, so the folder layout
is defined in exactly one place.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
from functools import cached_property
from pathlib import Path

import jsonschema
import yaml

SKILL_ROOT = Path(__file__).resolve().parent.parent
ASSETS = SKILL_ROOT / "assets"
SCHEMAS = ASSETS / "schemas"

CATEGORY_PREFIX = {
    "security": "CC",
    "availability": "A",
    "confidentiality": "C",
    "processing-integrity": "PI",
    "privacy": "P",
}


class AuditError(Exception):
    """A problem the operator can fix. The message says what is wrong and how to fix it."""


# --- file IO -----------------------------------------------------------------


class _StringDateLoader(yaml.SafeLoader):
    """YAML loader that keeps dates as ISO strings, so data round-trips through JSON Schema."""


_StringDateLoader.yaml_implicit_resolvers = {
    key: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(path: Path):
    with open(path, encoding="utf-8") as f:
        return yaml.load(f, Loader=_StringDateLoader)


def dump_yaml(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True, width=100)


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def dump_json(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items() if k} for row in csv.DictReader(f)]


def write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def schema_errors(data, schema_name: str) -> list[str]:
    """Return human-readable schema violations, each with the JSON path that failed."""
    schema = load_json(SCHEMAS / f"{schema_name}.schema.json")
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{where}: {err.message}")
    return errors


def load_criteria() -> list[dict]:
    return load_yaml(ASSETS / "criteria.yaml")["criteria"]


# --- the engagement folder ---------------------------------------------------


class Engagement:
    """One audit engagement on disk. See references/engagement-folder.md for the layout."""

    def __init__(self, root: Path | str):
        self.root = Path(root).resolve()
        self.config_path = self.root / "engagement.yaml"
        self.bundle = self.root / "bundle"
        self.manifest_path = self.bundle / "manifest.json"
        self.testplan_path = self.root / "testplan.csv"
        self.workpapers = self.root / "workpapers"
        self.opinion_path = self.root / "opinion.json"
        self.review = self.root / "review"
        self.qa_path = self.review / "qa.json"
        self.report = self.root / "report"

    # config

    @cached_property
    def config(self) -> dict:
        if not self.config_path.exists():
            raise AuditError(f"No engagement.yaml in {self.root}. Run `soc2.py init {self.root}` first.")
        data = load_yaml(self.config_path)
        errors = schema_errors(data, "engagement")
        if errors:
            raise AuditError("engagement.yaml is invalid:\n  " + "\n  ".join(errors))
        return data

    @property
    def report_type(self) -> int:
        return self.config["report_type"]

    @property
    def period(self) -> tuple[dt.date, dt.date]:
        """Start and end of the examination; a Type 1 'period' is the single as-of date."""
        if self.report_type == 2:
            p = self.config["period"]
            return parse_date(p["start"]), parse_date(p["end"])
        d = parse_date(self.config["as_of"])
        return d, d

    @property
    def period_label(self) -> str:
        start, end = self.period
        if self.report_type == 1:
            return f"as of {fmt_date(end)}"
        return f"throughout the period {fmt_date(start)} to {fmt_date(end)}"

    @cached_property
    def criteria(self) -> list[dict]:
        """Criteria in scope for this engagement, in report order."""
        cats = set(self.config["categories"])
        return [c for c in load_criteria() if c["category"] in cats]

    # bundle

    @cached_property
    def manifest(self) -> dict:
        if not self.manifest_path.exists():
            raise AuditError("No bundle/manifest.json. Run `soc2.py ingest` first.")
        return load_json(self.manifest_path)

    @cached_property
    def artifacts(self) -> dict[str, dict]:
        return {a["id"]: a for a in self.manifest["artifacts"]}

    def artifact_path(self, artifact_id: str) -> Path:
        return self.bundle / self.artifacts[artifact_id]["path"]

    @cached_property
    def controls(self) -> list[dict]:
        path = self.bundle / "controls.csv"
        if not path.exists():
            raise AuditError("No bundle/controls.csv. The connector must write the control matrix.")
        rows = read_csv(path)
        for row in rows:
            row["criteria"] = row.get("criteria", "").replace(",", " ").replace(";", " ").split()
        return rows

    @property
    def system_path(self) -> Path:
        """Management's system description: system.yaml at the root overrides the one the connector pulled."""
        root = self.root / "system.yaml"
        return root if root.exists() else self.bundle / "system.yaml"

    @cached_property
    def system(self) -> dict:
        return load_yaml(self.system_path) if self.system_path.exists() else {}

    def population(self, artifact_id: str) -> list[dict]:
        return read_csv(self.artifact_path(artifact_id))

    # workpapers

    def workpaper_path(self, control_id: str) -> Path:
        return self.workpapers / f"{safe_name(control_id)}.json"

    def workpaper_files(self) -> list[Path]:
        return sorted(self.workpapers.glob("*.json")) if self.workpapers.exists() else []

    def load_workpapers(self) -> dict[str, dict]:
        out = {}
        for path in self.workpaper_files():
            wp = load_json(path)
            out[wp.get("control_id", path.stem)] = wp
        return out

    def digest(self) -> str:
        """Hash over everything the report is built from. Sign-off is bound to this value."""
        h = hashlib.sha256()
        files = [self.config_path.name]
        files += [p.relative_to(self.root).as_posix() for p in [self.manifest_path, self.system_path, self.testplan_path, self.opinion_path, self.qa_path]]
        files += [p.relative_to(self.root).as_posix() for p in self.workpaper_files()]
        for rel in files:
            path = self.root / rel
            if not path.exists():
                continue
            if path == self.config_path:
                data = load_yaml(path)
                data.pop("signoff", None)
                content = json.dumps(data, sort_keys=True).encode()
            else:
                content = path.read_bytes()
            h.update(rel.encode() + b"\0" + hashlib.sha256(content).digest())
        return h.hexdigest()


def safe_name(control_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in control_id)


def fmt_date(d: dt.date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"
