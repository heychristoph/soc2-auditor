"""What a customer report may identify.

Workpapers keep names, inboxes and phone numbers, because those are the audit
record. The PDF does not. It may name the assertion signer and organizations.
It may not name anyone else, and it may not contain an email address or a phone
number. `validate --final` and `render` both use this module.
"""

from __future__ import annotations

import csv
import json
import re

from core import Engagement, load_yaml

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?:\+\d{8,15}\b|\(\d{3}\)\s*\d{3}[-.]\d{4}\b|\b\d{3}[-.)]\s*\d{3}[-.]\d{4}\b)")
PERSON = re.compile(r"^[A-Z][a-z]{2,} [A-Z][a-z]{2,}$")
# A given name and surname sitting where prose introduces a person.
INTRODUCED = re.compile(
    r"\b([A-Z][a-z]{2,} [A-Z][a-z]{2,})"
    r"(?="
    r", (?:intern|founder|employee|contractor|director|officer|analyst|engineer|owner)\b"
    r"| wrote\b| emailed\b| said\b"
    r"| \("
    r")"
)
BY_NAME = re.compile(r"\bby ([A-Z][a-z]{2,} [A-Z][a-z]{2,})\b")
PERSON_KEYS = {"full_name", "employee", "candidate", "requester"}
GENERIC_LOCAL = {"security", "support", "admin", "info", "noreply", "no-reply", "hello", "contact", "privacy", "legal", "sales", "billing", "postmaster"}
TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".yaml", ".yml"}


def activity(eng: Engagement, wp: dict) -> str:
    """Control wording printed in the report. Never the source description."""
    statement = (wp.get("statement") or "").strip()
    if statement:
        return statement
    for control in eng.controls:
        if control["id"] == wp["control_id"] and (control.get("title") or "").strip():
            return control["title"].strip()
    return wp["control_id"]


def report_system(eng: Engagement) -> dict | None:
    """Description printed in Section III.

    A draft pulled from the compliance system is evidence, not the description
    readers see. Management's file at the engagement root is printed, and so is
    a source file only when it is already marked management-approved.
    """
    root = eng.root / "system.yaml"
    if root.exists():
        return load_yaml(root)
    bundled = eng.bundle / "system.yaml"
    if bundled.exists():
        data = load_yaml(bundled)
        if data.get("status") == "management-approved":
            return data
    return None


def fragments(eng: Engagement) -> list[tuple[str, str]]:
    """Every string that can reach the PDF, with a label for the error."""
    out = []
    system = report_system(eng)
    if system:
        out.append(("system description", _flatten(system)))
    for cid, wp in sorted(eng.load_workpapers().items()):
        out.append((f"{cid} report wording", activity(eng, wp)))
        for procedure in wp.get("procedures") or []:
            out.append((f"{cid} procedure", procedure.get("text") or ""))
        if wp.get("scope_limitation"):
            out.append((f"{cid} scope limitation", wp["scope_limitation"]))
        rationale = (wp.get("design") or {}).get("rationale") or ""
        if rationale:
            out.append((f"{cid} design rationale", rationale))
        for item in wp.get("items") or []:
            if item.get("note"):
                out.append((f"{cid} sample note", item["note"]))
        for exc in wp.get("exceptions") or []:
            out.append((f"{cid} exception", exc.get("description") or ""))
            if exc.get("management_response"):
                out.append((f"{cid} management response", exc["management_response"]))
    if eng.opinion_path.exists():
        from core import load_json
        opinion = load_json(eng.opinion_path)
        if opinion.get("basis"):
            out.append(("opinion basis", opinion["basis"]))
        for item in opinion.get("scope_limitations") or []:
            out.append(("opinion scope limitation", item))
    return [(label, text) for label, text in out if text and text.strip()]


def check(eng: Engagement) -> tuple[list[str], list[str]]:
    """Errors name the string that would identify someone. Warnings cover a missing description."""
    errors = []
    warnings = []
    if report_system(eng) is None:
        warnings.append(
            "Section III does not include a system description. The source draft is evidence and is not printed. "
            "Write system.yaml at the engagement root for readers of the report. Name no one but management.name, "
            "and include no email address or phone number."
        )
    forbidden = _forbidden(eng)
    for label, text in fragments(eng):
        for hit in _leaks(text, forbidden):
            errors.append(f"{label}: {hit} The customer report does not identify that person. Keep it in the workpaper observations.")
    return errors, warnings


def redact(text: str, eng: Engagement) -> str:
    """Replace a leaked email, phone number or person in a report index entry."""
    if not text:
        return text
    cleaned = EMAIL.sub("[redacted]", text)
    cleaned = PHONE.sub("[redacted]", cleaned)
    for name in sorted(_forbidden(eng), key=len, reverse=True):
        cleaned = re.sub(rf"\b{re.escape(name)}\b", "[redacted]", cleaned, flags=re.I)
    return cleaned


def _forbidden(eng: Engagement) -> set[str]:
    """People the bundle identifies, minus the assertion signer and organization names."""
    found: set[str] = set()
    bundle = eng.bundle
    if not bundle.exists():
        return set()
    for path in bundle.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in EMAIL.finditer(text):
            local = match.group(0).split("@", 1)[0].lower()
            if re.fullmatch(r"[a-z]{9,}", local) and local not in GENERIC_LOCAL:
                found.add(local)
        if path.parent == bundle and path.name == "system.yaml":
            _harvest_prose(text, found)
        if path.parent == bundle and path.name == "controls.csv":
            for row in csv.DictReader(text.splitlines()):
                _harvest_prose(row.get("description") or "", found)
        if path.suffix.lower() == ".json":
            try:
                _walk(json.loads(text), found)
            except json.JSONDecodeError:
                pass
        if path.parent.name == "populations" and path.stem in ("hires", "terminations"):
            for row in csv.DictReader(text.splitlines()):
                _add_person(row.get("name") or "", found)
    allowed = _allowed(eng)
    tokens = {word.casefold() for name in allowed for word in re.split(r"[^A-Za-z]+", name) if len(word) > 2}
    kept = set()
    for name in found:
        if any(name.casefold() == a.casefold() or name.casefold() in a.casefold() for a in allowed):
            continue
        first = name.split()[0].casefold() if name.split() else ""
        if first and first in tokens:
            continue
        kept.add(name)
    return kept


def _allowed(eng: Engagement) -> set[str]:
    cfg = eng.config
    names = {cfg.get("service_organization") or "", cfg.get("system") or ""}
    mgmt = (cfg.get("management") or {}).get("name") or ""
    if mgmt:
        names.add(mgmt)
    for sub in cfg.get("subservice_organizations") or []:
        names.add(sub.get("name") or "")
    vendors = eng.bundle / "populations" / "vendors.csv"
    if vendors.exists():
        for row in csv.DictReader(vendors.read_text(encoding="utf-8", errors="replace").splitlines()):
            names.add(row.get("name") or "")
    return {n for n in names if n}


def _harvest_prose(text: str, found: set[str]) -> None:
    """Names introduced in the system description or a control description."""
    for match in INTRODUCED.finditer(text):
        found.add(match.group(1))
    for match in BY_NAME.finditer(text):
        found.add(match.group(1))


def _walk(obj, found: set[str]) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in PERSON_KEYS and isinstance(value, str):
                _add_person(value, found)
            else:
                _walk(value, found)
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, found)


def _add_person(value: str, found: set[str]) -> None:
    value = value.strip()
    if PERSON.match(value):
        found.add(value)


def _leaks(text: str, forbidden: set[str]) -> list[str]:
    found = []
    for match in EMAIL.finditer(text):
        found.append(f"contains the email address {match.group(0)}.")
    for match in PHONE.finditer(text):
        found.append(f"contains the phone number {match.group(0)}.")
    low = text.casefold()
    for name in sorted(forbidden):
        if re.search(rf"\b{re.escape(name)}\b", low, flags=re.I):
            found.append(f"names {name}.")
    return found


def _flatten(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(_flatten(v) for v in value.values())
    if isinstance(value, list):
        return "\n".join(_flatten(v) for v in value)
    return ""
