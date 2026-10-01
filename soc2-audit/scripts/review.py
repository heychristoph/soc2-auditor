"""`validate`, `rollup`, `packet` and `signoff`.

`validate` is the gate between phases: every conclusion must cite evidence that
exists in the bundle, cover exactly the planned sample, and agree with its own
results. Messages name the file and field so the agent can fix them directly.
"""

from __future__ import annotations

import datetime as dt
import random
from collections import defaultdict

from core import AuditError, Engagement, dump_json, dump_yaml, load_json, load_yaml, parse_date, read_csv, schema_errors, sha256_file
from planning import expected_plan
import privacy

DONE = ("no-exceptions", "exceptions", "design-deficiency", "not-tested")


def validate(eng: Engagement, final: bool = False) -> tuple[list[str], list[str]]:
    """Check workpapers (and, when `final`, opinion and QA). Returns (errors, warnings)."""
    errors, warnings = [], []
    plan_rows = {r["control_id"]: r for r in read_csv(eng.testplan_path)} if eng.testplan_path.exists() else {}
    if not plan_rows:
        return ["No testplan.csv. Run `soc2.py plan` and `soc2.py sample` first."], []
    workpapers = eng.load_workpapers()

    for cid in plan_rows:
        if cid not in workpapers:
            errors.append(f"{cid}: no workpaper; run `soc2.py sample`")
    for cid, wp in workpapers.items():
        e, w = _check_workpaper(eng, cid, wp, plan_rows.get(cid))
        errors += e
        warnings += w

    if final:
        errors += _check_opinion(eng, workpapers)
        errors += _check_qa(eng, workpapers)
        system = eng.system
        if not system:
            errors.append("no system description; management must provide system.yaml (see references/reporting.md)")
        elif system.get("status") != "management-approved":
            warnings.append("system.yaml is not management-approved; the AI Audit will say so")
        errors += _check_management(eng)
        leaked, notes = privacy.check(eng)
        errors += leaked
        warnings += notes
    return errors, warnings


def _check_management(eng: Engagement) -> list[str]:
    """The assertion is signed with a real person and role, not a blank or a placeholder."""
    mgmt = eng.config.get("management") or {}
    name = str(mgmt.get("name") or "").strip()
    title = str(mgmt.get("title") or "").strip()
    if _placeholder(name) or _placeholder(title):
        return ["engagement.yaml needs management.name and management.title: the real person responsible for the system and their role, taken from the evidence. Do not use a placeholder."]
    return []


def _placeholder(value: str) -> bool:
    if not value:
        return True
    low = value.lower()
    return any(mark in low for mark in ("[", "]", "placeholder", "name, title", "todo", "tbd", "n/a"))


def _check_workpaper(eng: Engagement, cid: str, wp: dict, plan_row: dict | None) -> tuple[list[str], list[str]]:
    where = f"workpapers/{eng.workpaper_path(cid).name}"
    errors = [f"{where}: {m}" for m in schema_errors(wp, "workpaper")]
    warnings: list[str] = []
    if errors:
        return errors, warnings
    if plan_row is None:
        return [f"{where}: control {cid} is not in testplan.csv"], warnings
    if wp["plan"] != expected_plan(eng, plan_row):
        errors.append(f"{where}: plan does not match testplan.csv and the sampling seed; do not edit `plan`, re-run `soc2.py sample`")

    concl = wp["conclusion"]
    if concl == "pending":
        return [f"{where}: conclusion is still 'pending'"], warnings
    for field in ("confidence", "prepared_by"):
        if not wp.get(field):
            errors.append(f"{where}: {field} is required")

    cite = lambda ids, label: [f"{where}: {label} cites {i}, which is not in bundle/manifest.json" for i in ids if i not in eng.artifacts]

    design = wp["design"]
    if design["effective"] is None:
        errors.append(f"{where}: design.effective must be true or false")
    if not design["rationale"].strip():
        errors.append(f"{where}: design.rationale is empty")
    if not design["evidence"]:
        errors.append(f"{where}: design.evidence must cite at least one artifact (policy, procedure or configuration)")
    errors += cite(design["evidence"], "design.evidence")
    if design["effective"] is False and concl != "design-deficiency":
        errors.append(f"{where}: design.effective is false, so conclusion must be 'design-deficiency'")

    if concl == "not-tested":
        if not (wp.get("scope_limitation") or "").strip():
            errors.append(f"{where}: conclusion 'not-tested' needs scope_limitation (why the control could not be tested)")
        return errors, warnings

    if not wp["procedures"]:
        errors.append(f"{where}: procedures is empty; list what was done (inquiry, inspection, observation, reperformance)")
    if concl != "design-deficiency":
        if not wp["attributes"]:
            errors.append(f"{where}: attributes is empty; define what must be true for each sampled item")
        planned = wp["plan"]["sample"]
        tested = [i["id"] for i in wp["items"]]
        if sorted(tested) != sorted(planned):
            missing, extra = sorted(set(planned) - set(tested)), sorted(set(tested) - set(planned))
            errors.append(f"{where}: items must match plan.sample exactly (missing {missing}, unexpected {extra})")
        failed_items = set()
        start, end = eng.period
        for item in wp["items"]:
            missing_attrs = sorted(set(wp["attributes"]) - set(item["results"]))
            if missing_attrs:
                errors.append(f"{where}: item {item['id']} has no result for attributes {missing_attrs}")
            if not item["evidence"] and any(v == "pass" for v in item["results"].values()):
                errors.append(f"{where}: item {item['id']} passes an attribute but cites no evidence; a pass must be supported")
            errors += cite(item["evidence"], f"item {item['id']}")
            if any(v == "n/a" for v in item["results"].values()) and not item.get("note"):
                errors.append(f"{where}: item {item['id']} marks an attribute n/a without a note explaining why")
            if any(v == "fail" for v in item["results"].values()):
                failed_items.add(item["id"])
            for ev in item["evidence"]:
                d = parse_date(eng.artifacts.get(ev, {}).get("date"))
                if d and eng.report_type == 2 and not (start - dt.timedelta(days=31) <= d <= end + dt.timedelta(days=31)):
                    warnings.append(f"{where}: item {item['id']} relies on {ev} dated {d}, outside the period")
        excepted = {x["item"] for x in wp["exceptions"]}
        for item_id in sorted(failed_items - excepted):
            errors.append(f"{where}: item {item_id} failed an attribute but has no entry in exceptions")
        if wp["plan"]["population"] and wp["plan"]["population"]["source"].startswith("PO-") and eng.report_type == 2:
            pc = wp.get("population_check")
            if not pc:
                errors.append(f"{where}: population_check is required; test completeness of {wp['plan']['population']['source']} against a source record")
            else:
                errors += cite(pc["evidence"], "population_check")
                if pc["complete"] is False and "population" not in excepted:
                    errors.append(f"{where}: population_check.complete is false, so add an exception with item 'population'")

    for x in wp["exceptions"]:
        errors += cite(x["evidence"], f"exception on {x['item']}")
        if x["item"] not in wp["plan"]["sample"] and x["item"] not in ("design", "population"):
            errors.append(f"{where}: exception item '{x['item']}' is not in the sample (use 'design' or 'population' for other exceptions)")
    if wp["exceptions"] and concl == "no-exceptions":
        errors.append(f"{where}: exceptions are listed, so conclusion cannot be 'no-exceptions'")
    if not wp["exceptions"] and concl == "exceptions":
        errors.append(f"{where}: conclusion is 'exceptions' but the exceptions list is empty")
    return errors, warnings


def _check_opinion(eng: Engagement, workpapers: dict) -> list[str]:
    if not eng.opinion_path.exists():
        return ["opinion.json is missing; see references/evaluating.md"]
    op = load_json(eng.opinion_path)
    errors = [f"opinion.json: {m}" for m in schema_errors(op, "opinion")]
    if errors:
        return errors
    in_scope = {c["id"] for c in eng.criteria}
    for c in op["criteria_not_met"]:
        if c["criterion"] not in in_scope:
            errors.append(f"opinion.json: {c['criterion']} is not in scope")
        errors += [f"opinion.json: {c['criterion']} cites unknown control {x}" for x in c["controls"] if x not in workpapers]
    kind = op["opinion"]
    modified = bool(op["criteria_not_met"] or op["scope_limitations"])
    if kind == "unmodified" and modified:
        errors.append("opinion.json: an unmodified opinion cannot list criteria not met or scope limitations")
    if kind in ("qualified", "adverse") and not modified:
        errors.append(f"opinion.json: a {kind} opinion needs criteria_not_met or scope_limitations")
    if kind == "disclaimer" and not op["scope_limitations"]:
        errors.append("opinion.json: a disclaimer needs scope_limitations")
    if kind != "unmodified" and not op["basis"].strip():
        errors.append("opinion.json: basis is required for a modified opinion")
    uncovered = sorted(in_scope - {x for wp in workpapers.values() for x in wp["criteria"]} - {c["criterion"] for c in op["criteria_not_met"]})
    if uncovered:
        errors.append(f"opinion.json: criteria {uncovered} have no tested control; list them in criteria_not_met or add controls")
    return errors


def _check_qa(eng: Engagement, workpapers: dict) -> list[str]:
    if not eng.qa_path.exists():
        return ["review/qa.json is missing; run the QA review (references/qa-review.md)"]
    qa = load_json(eng.qa_path)
    errors = [f"review/qa.json: {m}" for m in schema_errors(qa, "qa")]
    if errors:
        return errors
    latest = {r["control_id"]: r for r in qa["reviews"]}
    for cid in workpapers:
        r = latest.get(cid)
        if not r:
            errors.append(f"{cid}: no QA review")
        elif r["workpaper_sha256"] != sha256_file(eng.workpaper_path(cid)):
            errors.append(f"{cid}: workpaper changed after QA review; QA must review it again")
        elif r["verdict"] != "agree":
            errors.append(f"{cid}: QA disagrees ({'; '.join(r['issues'])[:200]}); resolve, then re-review")
    return errors


def record_qa(eng: Engagement, control_id: str, verdict: str, issues: list[str], checked: list[str], reviewer: str) -> None:
    """Add or replace the QA review of one workpaper, bound to the workpaper's current hash."""
    path = eng.workpaper_path(control_id)
    if not path.exists():
        raise AuditError(f"No workpaper for {control_id}.")
    if verdict == "disagree" and not issues:
        raise AuditError("A 'disagree' verdict needs at least one --issue explaining what is wrong.")
    unknown = [e for e in checked if e not in eng.artifacts]
    if unknown:
        raise AuditError(f"--checked cites artifacts not in the bundle: {unknown}")
    qa = load_json(eng.qa_path) if eng.qa_path.exists() else {"schema_version": 1, "reviews": []}
    qa["reviews"] = [r for r in qa["reviews"] if r["control_id"] != control_id]
    qa["reviews"].append({"control_id": control_id, "workpaper_sha256": sha256_file(path), "verdict": verdict,
                          "issues": issues, "evidence_checked": checked, "reviewed_by": reviewer})
    qa["reviews"].sort(key=lambda r: r["control_id"])
    dump_json(qa, eng.qa_path)


# --- rollup ------------------------------------------------------------------


def rollup(eng: Engagement) -> str:
    """Criterion-level summary that feeds the opinion decision. Written to review/rollup.md."""
    workpapers = eng.load_workpapers()
    by_crit = defaultdict(list)
    for cid, wp in workpapers.items():
        for c in wp["criteria"]:
            by_crit[c].append((cid, wp["conclusion"], len(wp["exceptions"]), wp.get("confidence")))
    lines = [f"# Criterion rollup: {eng.config['service_organization']} (Type {eng.report_type})", "",
             "| Criterion | Controls (conclusion, exceptions) | Needs judgment |", "|---|---|---|"]
    for crit in eng.criteria:
        entries = by_crit.get(crit["id"], [])
        cell = "; ".join(f"{cid} {concl} ({n})" for cid, concl, n, _ in entries) or "**no controls**"
        clean = [e for e in entries if e[1] == "no-exceptions"]
        flag = ""
        if not entries:
            flag = "No control addresses this criterion"
        elif not clean:
            flag = "Every control has exceptions, a design deficiency or was not tested"
        elif len(clean) < len(entries):
            flag = "Some controls have exceptions; decide whether the others still meet the criterion"
        lines.append(f"| {crit['id']} | {cell} | {flag} |")
    text = "\n".join(lines) + "\n"
    eng.review.mkdir(parents=True, exist_ok=True)
    (eng.review / "rollup.md").write_text(text, encoding="utf-8")
    return text


# --- review packet -------------------------------------------------------------

SPOT_CHECKS = 5  # Passing controls to re-read; enough to catch systematic errors cheaply.


def packet(eng: Engagement) -> str:
    """The record of what the AI Audit concluded. Written to review/packet.md."""
    workpapers = eng.load_workpapers()
    op = load_json(eng.opinion_path) if eng.opinion_path.exists() else None
    errors, warnings = validate(eng, final=True)

    def ev_links(ids):
        return ", ".join(f"[{i}](../bundle/{eng.artifacts[i]['path']})" for i in ids if i in eng.artifacts) or "none"

    out = [f"# Review packet: {eng.config['service_organization']}, AI Audit (SOC 2 Type {eng.report_type} procedures)", "",
           "This packet supports an AI Audit. It is not an official SOC 2 audit. It is the internal record: it quotes observations and the source control text, and it is not the customer report.", "",
           f"Period: {eng.period_label}. Digest: `{eng.digest()[:16]}`.", ""]
    if errors:
        out += ["## Blocking issues", "", *[f"- {e}" for e in errors], ""]
    out += ["## Opinion", ""]
    if op:
        out += [f"**{op['opinion'].capitalize()}** (prepared by {op['prepared_by']}).", ""]
        if op["basis"]:
            out += [op["basis"], ""]
    else:
        out += ["Not yet decided.", ""]

    sections = [
        ("Exceptions", [w for w in workpapers.values() if w["exceptions"]]),
        ("Design deficiencies", [w for w in workpapers.values() if w["conclusion"] == "design-deficiency"]),
        ("Not tested (scope limitations)", [w for w in workpapers.values() if w["conclusion"] == "not-tested"]),
        ("Low or medium confidence conclusions", [w for w in workpapers.values() if w.get("confidence") in ("low", "medium")]),
        ("Observations raised by the tester", [w for w in workpapers.values() if w.get("observations")]),
    ]
    for title, wps in sections:
        out += [f"## {title} ({len(wps)})", ""]
        for w in wps:
            out.append(f"### {w['control_id']}: {privacy.activity(eng, w)}")
            out.append(f"Conclusion: {w['conclusion']}, confidence: {w.get('confidence')}. Criteria: {', '.join(w['criteria'])}.")
            for x in w["exceptions"]:
                out.append(f"- Exception ({x['item']}): {x['description']} Evidence: {ev_links(x['evidence'])}")
            if w.get("scope_limitation"):
                out.append(f"- Scope limitation: {w['scope_limitation']}")
            for o in w.get("observations") or []:
                out.append(f"- Observation: {o}")
            out.append("")

    passing = sorted(cid for cid, w in workpapers.items() if w["conclusion"] == "no-exceptions")
    rng = random.Random(eng.digest())
    picks = sorted(rng.sample(passing, min(SPOT_CHECKS, len(passing))))
    out += [f"## Spot checks ({len(picks)} passing controls, chosen at random)", "",
            "Re-perform one sample item for each and confirm the evidence supports the conclusion.", ""]
    for cid in picks:
        w = workpapers[cid]
        item = w["items"][0] if w["items"] else None
        out.append(f"- **{cid}**: {privacy.activity(eng, w)}. " + (f"Item {item['id']}: evidence {ev_links(item['evidence'])}" if item else "No items."))
    if warnings:
        out += ["", "## Warnings", "", *[f"- {w}" for w in warnings]]
    out += ["", "## Sign-off", "",
            "Set management.name and management.title to the real person and role, then sign with "
            "`soc2.py signoff <engagement> --model \"<model name>\"` and `soc2.py render`. "
            "The PDF shows that model name, the title AI Auditor, management's name and title, and the signature date. "
            "It is an AI Audit, not an official SOC 2 audit. Any later change to the work clears the signature.", ""]
    text = "\n".join(out)
    eng.review.mkdir(parents=True, exist_ok=True)
    (eng.review / "packet.md").write_text(text, encoding="utf-8")
    return text


# --- sign-off ------------------------------------------------------------------


def signoff(eng: Engagement, model: str) -> str:
    """Record the model that ran the AI Audit, bound to the digest of the work."""
    model = (model or "").strip()
    if not model:
        raise AuditError("Sign-off needs --model, the name of the model that ran the AI Audit.")
    errors, _ = validate(eng, final=True)
    if errors:
        raise AuditError("Cannot sign off while validation fails:\n  " + "\n  ".join(errors[:20]))
    digest = eng.digest()
    config = load_yaml(eng.config_path)
    config["service_auditor"] = "AI Audit"
    config["signoff"] = {"model": model, "date": dt.date.today().isoformat(), "digest": digest}
    dump_yaml(config, eng.config_path)
    # service_auditor is part of the digest. Recompute after writing it, then store that digest.
    digest = eng.digest()
    config = load_yaml(eng.config_path)
    config["signoff"]["digest"] = digest
    dump_yaml(config, eng.config_path)
    return digest


def signed_off(eng: Engagement) -> bool:
    s = load_yaml(eng.config_path).get("signoff") or {}
    return bool(s.get("model")) and s.get("digest") == eng.digest()
