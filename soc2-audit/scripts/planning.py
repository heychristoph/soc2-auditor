"""`plan` and `sample`: the test plan and reproducible sample selection.

testplan.csv is the auditor's document: how often each control operates, whether
it is manual or automated, and which population it draws from. `sample` turns it
into workpaper skeletons with a seeded, repeatable sample for every control.
"""

from __future__ import annotations

import datetime as dt
import random

from core import ASSETS, AuditError, Engagement, dump_json, load_json, load_yaml, parse_date, read_csv, write_csv

FREQUENCIES = ["annual", "semiannual", "quarterly", "monthly", "weekly", "daily", "multiple-daily", "event", "continuous"]
NATURES = ["manual", "automated", "itdm"]  # itdm: IT-dependent manual
COLUMNS = ["control_id", "frequency", "nature", "population", "sample_size", "notes"]


def plan(eng: Engagement) -> list[str]:
    """Create or refresh testplan.csv. Keeps auditor edits; returns rows that still need input."""
    existing = {r["control_id"]: r for r in read_csv(eng.testplan_path)} if eng.testplan_path.exists() else {}
    rows = []
    for c in eng.controls:
        row = existing.get(c["id"]) or {
            "control_id": c["id"],
            "frequency": c.get("frequency", "").lower(),
            "nature": c.get("nature", "").lower(),
            "population": c.get("population", ""),
            "sample_size": "",
            "notes": "",
        }
        rows.append(row)
    removed = sorted(set(existing) - {c["id"] for c in eng.controls})
    write_csv(eng.testplan_path, rows, COLUMNS)
    todo = [f"{r['control_id']}: set {', '.join(p for p in ('frequency', 'nature') if not r[p])}" for r in rows if not r["frequency"] or not r["nature"]]
    todo += [f"{cid}: no longer in controls.csv; row dropped" for cid in removed]
    return todo


def sample(eng: Engagement, force: bool = False) -> list[str]:
    """Validate testplan.csv and write workpaper skeletons. Returns a log of what was written."""
    rows = _validated_plan(eng)
    controls = {c["id"]: c for c in eng.controls}
    log = []
    for row in rows:
        c = controls[row["control_id"]]
        planned = expected_plan(eng, row)
        path = eng.workpaper_path(c["id"])
        if path.exists():
            wp = load_json(path)
            if wp.get("plan") == planned:
                continue
            if wp.get("conclusion") not in (None, "pending") and not force:
                raise AuditError(f"{c['id']}: the test plan changed but the workpaper already has results. "
                                 "Re-run with --force to discard them, or restore the previous testplan.csv row.")
        dump_json(skeleton(c, planned), path)
        log.append(f"{c['id']}: {planned['sample_size']} of {planned['population']['size'] if planned['population'] else 1} ({row['frequency']}, {row['nature']})")
    return log


def expected_plan(eng: Engagement, row: dict) -> dict:
    """The plan block `sample` writes for a testplan row. Deterministic for a given seed."""
    rules = load_yaml(ASSETS / "sampling.yaml")
    cid, freq, nature = row["control_id"], row["frequency"], row["nature"]
    seed = f"{eng.config['sampling_seed']}:{cid}"
    rng = random.Random(seed)
    start, end = eng.period

    if row["population"]:
        items = [r["id"] for r in eng.population(row["population"]) if _in_period(eng, r.get("date"))]
        population = {"source": row["population"], "size": len(items)}
    elif freq in ("continuous",) or nature == "automated":
        items, population = ["instance-1"], None
    elif eng.report_type == 1:
        items, population = ["latest"], None  # the most recent performance on or before the as-of date
    else:
        items = occurrences(freq, start, end)
        population = {"source": "periods", "size": len(items)}

    if eng.report_type == 1:
        size = min(rules["type1"], len(items))
    elif row["sample_size"]:
        size = min(int(row["sample_size"]), len(items))
    elif nature == "automated" or freq == "continuous":
        size = min(rules["automated"], len(items))
    elif freq == "event" or row["population"]:
        size = _event_size(rules["event"], len(items))
    else:
        size = min(rules["periodic"][freq], len(items))

    chosen = sorted(rng.sample(items, size)) if size < len(items) else list(items)
    return {"frequency": freq, "nature": nature, "population": population, "sample_size": len(chosen), "sample": chosen, "seed": seed}


def skeleton(control: dict, planned: dict) -> dict:
    return {
        "schema_version": 1,
        "control_id": control["id"],
        "control": control["description"],
        "criteria": control["criteria"],
        "plan": planned,
        "design": {"effective": None, "rationale": "", "evidence": []},
        "procedures": [],
        "attributes": {},
        "items": [{"id": item, "results": {}, "evidence": [], "note": ""} for item in planned["sample"]],
        "exceptions": [],
        "population_check": None,
        "conclusion": "pending",
        "scope_limitation": None,
        "observations": [],
        "confidence": None,
        "prepared_by": None,
    }


def occurrences(freq: str, start: dt.date, end: dt.date) -> list[str]:
    """Calendar occurrences of a periodic control that fall in [start, end], as stable labels."""
    if freq == "annual":
        return sorted({str(y) for y in range(start.year, end.year + 1)})
    if freq in ("semiannual", "quarterly", "monthly"):
        step = {"semiannual": 6, "quarterly": 3, "monthly": 1}[freq]
        labels, y, m = [], start.year, ((start.month - 1) // step) * step + 1
        while dt.date(y, m, 1) <= end:
            if freq == "monthly":
                labels.append(f"{y}-{m:02d}")
            elif freq == "quarterly":
                labels.append(f"{y}-Q{(m - 1) // 3 + 1}")
            else:
                labels.append(f"{y}-H{(m - 1) // 6 + 1}")
            m += step
            if m > 12:
                y, m = y + 1, m - 12
        return labels
    if freq == "weekly":
        labels, d = [], start
        while d <= end:
            iso = d.isocalendar()
            label = f"{iso[0]}-W{iso[1]:02d}"
            if label not in labels:
                labels.append(label)
            d += dt.timedelta(days=1)
        return labels
    if freq in ("daily", "multiple-daily"):
        return [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    raise AuditError(f"Frequency '{freq}' has no calendar occurrences; give the control a population file.")


def _event_size(table: list[dict], n: int) -> int:
    for rule in table:
        if rule["max_population"] is None or n <= rule["max_population"]:
            return n if rule["size"] == "all" else min(rule["size"], n)
    return n


def _in_period(eng: Engagement, value: str | None) -> bool:
    d = parse_date(value)
    start, end = eng.period
    if eng.report_type == 1:
        return d is None or d <= end
    return d is not None and start <= d <= end


def _validated_plan(eng: Engagement) -> list[dict]:
    if not eng.testplan_path.exists():
        raise AuditError("No testplan.csv. Run `soc2.py plan` first.")
    rows = read_csv(eng.testplan_path)
    control_ids = {c["id"] for c in eng.controls}
    errors = []
    for i, r in enumerate(rows, start=2):
        where = f"testplan.csv line {i} ({r.get('control_id')})"
        if r.get("control_id") not in control_ids:
            errors.append(f"{where}: unknown control")
        if r.get("frequency") not in FREQUENCIES:
            errors.append(f"{where}: frequency must be one of {', '.join(FREQUENCIES)}")
        if r.get("nature") not in NATURES:
            errors.append(f"{where}: nature must be one of {', '.join(NATURES)}")
        if r.get("frequency") == "event" and not r.get("population"):
            errors.append(f"{where}: event-driven controls need a population artifact ID (PO-...)")
        if r.get("population") and r["population"] not in eng.artifacts:
            errors.append(f"{where}: population {r['population']} is not in the bundle")
        if r.get("sample_size"):
            if not r["sample_size"].isdigit():
                errors.append(f"{where}: sample_size must be a whole number or empty")
            elif not r.get("notes"):
                errors.append(f"{where}: explain a sample_size override in notes")
    missing = control_ids - {r.get("control_id") for r in rows}
    if missing:
        errors.append(f"testplan.csv is missing controls {sorted(missing)}; run `soc2.py plan` again")
    if errors:
        raise AuditError("testplan.csv needs fixes:\n  " + "\n  ".join(errors))
    return rows
