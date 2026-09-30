"""`check`: bundle integrity and coverage, before any testing starts.

Produces review/coverage.md (criterion -> controls -> evidence) and
review/requests.csv (the information request list for the service organization).
"""

from __future__ import annotations

from collections import defaultdict

from core import Engagement, load_criteria, parse_date, sha256_file, write_csv

SYSTEM_FIELDS = ["overview", "services", "commitments", "components"]


def run(eng: Engagement) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    arts = eng.artifacts
    known_criteria = {c["id"] for c in load_criteria()}
    in_scope = {c["id"] for c in eng.criteria}
    start, end = eng.period
    requests = []

    # Integrity: every registered file is present and unchanged since ingest.
    for a in arts.values():
        path = eng.bundle / a["path"]
        if not path.exists():
            errors.append(f"{a['id']}: file {a['path']} is missing from the bundle")
        elif sha256_file(path) != a["sha256"]:
            errors.append(f"{a['id']}: file {a['path']} changed after ingest (hash mismatch); re-run ingest")
    registered = {a["path"] for a in arts.values()} | {"manifest.json"}
    for path in eng.bundle.rglob("*"):
        if path.is_file() and path.relative_to(eng.bundle).as_posix() not in registered:
            warnings.append(f"bundle/{path.relative_to(eng.bundle).as_posix()} is not in the manifest and will be ignored")
    warnings += [f"ingest: {w}" for w in eng.manifest.get("warnings", [])]

    # Control matrix.
    controls = eng.controls
    seen = set()
    by_criterion = defaultdict(list)
    for c in controls:
        cid = c["id"]
        if cid in seen:
            errors.append(f"controls.csv: duplicate control ID {cid}")
        seen.add(cid)
        if not c.get("description"):
            errors.append(f"{cid}: control has no description")
        unknown = [x for x in c["criteria"] if x not in known_criteria]
        if unknown:
            errors.append(f"{cid}: unknown criteria {unknown} (use IDs like CC6.1, A1.2)")
        if not c["criteria"]:
            warnings.append(f"{cid}: control is not mapped to any criterion")
        elif not any(x in in_scope for x in c["criteria"]):
            warnings.append(f"{cid}: maps only to criteria outside the engagement scope ({' '.join(c['criteria'])})")
        for x in c["criteria"]:
            by_criterion[x].append(cid)
        pop = c.get("population")
        if pop and pop not in arts:
            errors.append(f"{cid}: population {pop} is not in the bundle")

    evidence_by_control = defaultdict(list)
    for a in arts.values():
        for cid in a.get("controls", []):
            evidence_by_control[cid].append(a["id"])
            if cid not in seen:
                warnings.append(f"{a['id']}: linked to unknown control {cid}")

    for crit in sorted(in_scope, key=_order):
        if not by_criterion.get(crit):
            warnings.append(f"{crit}: no control addresses this criterion (possible design gap)")
            requests.append({"id": f"R-{len(requests) + 1:03d}", "control": "", "criterion": crit,
                             "request": f"Identify the controls that address {crit}, or confirm none exist.", "reason": "no mapped control"})
    for c in controls:
        if not evidence_by_control.get(c["id"]) and not c.get("population"):
            requests.append({"id": f"R-{len(requests) + 1:03d}", "control": c["id"], "criterion": " ".join(c["criteria"]),
                             "request": f"Provide evidence that control {c['id']} is in place ({c.get('title') or c['description'][:80]}).",
                             "reason": "no evidence linked"})

    # Populations: dates and IDs.
    for a in arts.values():
        if a["kind"] != "population":
            continue
        rows = eng.population(a["id"])
        ids = [r["id"] for r in rows]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            errors.append(f"{a['id']}: duplicate item IDs {sorted(dupes)[:5]}")
        if eng.report_type == 2:
            outside = [r["id"] for r in rows if (d := parse_date(r["date"])) and not (start <= d <= end)]
            if outside:
                warnings.append(f"{a['id']}: {len(outside)} items dated outside the period ({', '.join(outside[:5])}); they will be excluded from sampling")

    # System description (management's responsibility).
    system = eng.system
    if not system:
        warnings.append("no system description; Section III cannot be rendered until management provides system.yaml")
        requests.append({"id": f"R-{len(requests) + 1:03d}", "control": "", "criterion": "", "request": "Provide the system description (system.yaml).", "reason": "missing"})
    else:
        empty = [f for f in SYSTEM_FIELDS if not system.get(f)]
        if empty:
            warnings.append(f"{eng.system_path.relative_to(eng.root)}: empty fields {empty}; management must complete them")
        if system.get("status") != "management-approved":
            warnings.append("system.yaml: status is not 'management-approved'; the report stays a draft until management approves the description")

    _write_coverage(eng, by_criterion, evidence_by_control)
    write_csv(eng.review / "requests.csv", requests, ["id", "control", "criterion", "request", "reason"])
    return errors, warnings


def _order(criterion_id: str):
    order = {c["id"]: i for i, c in enumerate(load_criteria())}
    return order.get(criterion_id, 999)


def _write_coverage(eng: Engagement, by_criterion, evidence_by_control) -> None:
    lines = [f"# Coverage: {eng.config['service_organization']}", "", "| Criterion | Controls | Evidence items |", "|---|---|---|"]
    for crit in eng.criteria:
        cids = by_criterion.get(crit["id"], [])
        ev = sum(len(evidence_by_control.get(c, [])) for c in cids)
        lines.append(f"| {crit['id']} | {', '.join(cids) or '**none**'} | {ev} |")
    eng.review.mkdir(parents=True, exist_ok=True)
    (eng.review / "coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
