"""`render`: build the report PDF, workpaper spreadsheet and evidence index from the workpapers.

All report text comes from assets/report/report-text.yaml plus the validated
workpapers, opinion and system description. Nothing is written freehand here,
so the PDF cannot disagree with the work behind it.
"""

from __future__ import annotations

import csv
import datetime as dt
import re
import shutil
import tempfile
from pathlib import Path

from core import ASSETS, AuditError, Engagement, dump_json, fmt_date, load_json, load_yaml, parse_date
from review import signed_off, validate
import privacy

CATEGORY_NAMES = {"security": "security", "availability": "availability", "confidentiality": "confidentiality",
                  "processing-integrity": "processing integrity", "privacy": "privacy"}


class _Keep(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render(eng: Engagement) -> dict[str, Path]:
    errors, warnings = validate(eng, final=True)
    if errors:
        raise AuditError("Fix validation errors before rendering:\n  " + "\n  ".join(errors[:30]))
    final = signed_off(eng)
    text = load_yaml(ASSETS / "report" / "report-text.yaml")
    data = _report_data(eng, text, final)
    eng.report.mkdir(parents=True, exist_ok=True)
    stem = f"soc2-type{eng.report_type}-{re.sub(r'[^a-z0-9]+', '-', eng.config['service_organization'].lower()).strip('-')}"
    pdf = eng.report / f"{stem}{'' if final else '-DRAFT'}.pdf"
    _compile_pdf(data, pdf)
    dump_json(data, eng.report / "report-data.json")
    xlsx = eng.report / "workpapers.xlsx"
    _write_xlsx(eng, xlsx)
    index = eng.report / "evidence-index.csv"
    _write_evidence_index(eng, index)
    return {"pdf": pdf, "xlsx": xlsx, "evidence_index": index, "final": final, "warnings": warnings}


# --- report content --------------------------------------------------------------


def _vars(eng: Engagement, text: dict, opinion: dict) -> _Keep:
    cfg = eng.config
    cats = [CATEGORY_NAMES[c] for c in cfg["categories"]]
    cat_text = _join(cats)
    t2 = eng.report_type == 2
    subs = [s["name"] for s in cfg.get("subservice_organizations") or []]
    has_complementary = bool(subs or eng.system.get("cuecs"))
    start, end = eng.period
    v = _Keep(
        org=cfg["service_organization"], system=cfg["system"], auditor="AI Audit",
        model=(cfg.get("signoff") or {}).get("model") or "the model that has not yet signed this AI Audit",
        period=eng.period_label, period_dates=f"{fmt_date(start)} to {fmt_date(end)}" if t2 else fmt_date(end),
        categories=cat_text, categories_title=cat_text.title().replace(" And ", " and "),
        subservice=("the subservice organization " if len(subs) == 1 else "the subservice organizations ") + _join(subs) if subs else "",
        description_criteria=text["standards"]["description_criteria"], trust_services_criteria=text["standards"]["trust_services_criteria"],
        and_oe=" and Operating Effectiveness" if t2 else "", and_oe_lc=" and operating effectiveness" if t2 else "",
        or_oe=" or operating effectiveness" if t2 else "",
        tests_clause=", including the description of tests of controls and their results in Section IV," if t2 else "",
        and_operated=" and operated effectively" if t2 else "", and_operating=" and operating effectively" if t2 else "", or_did_not_operate=" or did not operate effectively" if t2 else "",
        oe_procedure=text["section1"]["auditor_responsibilities"]["oe_procedure"] if t2 else "",
        complementary=text["section1"]["opinion"]["complementary"] if has_complementary else "",
        complementary_mgmt=text["section2"]["complementary_mgmt"] if has_complementary else "",
        basis_heading={"qualified": "Qualified", "adverse": "Adverse", "disclaimer": "Disclaimer of"}.get(opinion["opinion"], ""),
    )
    return v


def _join(names: list[str]) -> str:
    if len(names) <= 2:
        return " and ".join(names)
    return ", ".join(names[:-1]) + ", and " + names[-1]


def _fill(s: str, v: _Keep) -> str:
    for _ in range(3):  # placeholders can contain placeholders
        s = s.format_map(v)
    s = re.sub(r"(?<!\.)\.\.(?!\.)", ".", s)  # "Inc." at the end of a sentence
    return " ".join(s.split())


def _report_data(eng: Engagement, text: dict, final: bool) -> dict:
    opinion = load_json(eng.opinion_path)
    v = _vars(eng, text, opinion)
    f = lambda s: _fill(s, v)
    cfg = eng.config
    t2 = eng.report_type == 2
    s1 = text["section1"]
    signoff = cfg.get("signoff") or {}
    model = (signoff.get("model") or "").strip()
    if not model or not signoff.get("date"):
        raise AuditError("Run `soc2.py signoff --model \"<model name>\"` before render. The report is signed with that model name, the title AI Auditor, and the date of the signature.")
    report_date = fmt_date(parse_date(signoff["date"]))
    mgmt = cfg.get("management") or {}
    mgmt_name = str(mgmt.get("name") or "").strip()
    mgmt_title = str(mgmt.get("title") or "").strip()

    # Section I
    notice = s1["notice"] if signoff.get("model") else s1["notice_unsigned"]
    b = [{"kind": "para", "text": f(notice)}, {"kind": "para", "text": f(s1["addressee"])}, {"kind": "heading", "text": "Scope"},
         {"kind": "para", "text": f(s1["scope"]["type2" if t2 else "type1"])}]
    if not t2:
        b.append({"kind": "para", "text": f(s1["type1_no_oe"])})
    if cfg.get("subservice_organizations"):
        b.append({"kind": "para", "text": f(s1["subservice"])})
    if eng.system.get("cuecs"):
        b.append({"kind": "para", "text": f(s1["cuec"])})
    b += [{"kind": "heading", "text": s1["org_responsibilities"]["heading"]}, {"kind": "para", "text": f(s1["org_responsibilities"]["text"])},
          {"kind": "heading", "text": s1["auditor_responsibilities"]["heading"]}, {"kind": "para", "text": f(s1["auditor_responsibilities"]["text"])},
          {"kind": "para", "text": f(s1["auditor_responsibilities"]["procedures_intro"])},
          {"kind": "list", "items": [f(p) for p in s1["auditor_responsibilities"]["procedures"] if f(p)]},
          {"kind": "para", "text": f(s1["auditor_responsibilities"]["independence"])},
          {"kind": "heading", "text": s1["limitations"]["heading"]}, {"kind": "para", "text": f(s1["limitations"]["text"])}]
    if t2:
        b += [{"kind": "heading", "text": s1["tests_description"]["heading"]}, {"kind": "para", "text": f(s1["tests_description"]["text"])}]
    if opinion["opinion"] != "unmodified":
        b += [{"kind": "heading", "text": f(s1["basis"]["heading"])}, {"kind": "para", "text": opinion["basis"]}]
    b.append({"kind": "heading", "text": s1["opinion"]["heading"]})
    kind = opinion["opinion"]
    if kind == "disclaimer":
        b.append({"kind": "para", "text": f(s1["opinion"]["disclaimer"])})
    else:
        items = s1["opinion"]["items"]
        chosen = [items["description"], items["design"]] + ([items["operating"]] if t2 else [])
        if kind == "adverse":
            adverse = s1["opinion"]["adverse_items"]
            chosen = [items["description"], adverse["design"]] + ([adverse["operating"]] if t2 else [])
        if not t2:
            chosen[-1] = chosen[-1].rstrip(";") + "."
        b += [{"kind": "para", "text": f(s1["opinion"][kind])}, {"kind": "list", "items": [f(x) for x in chosen], "enum": True}]
    b += [{"kind": "heading", "text": s1["restricted_use"]["heading"]}, {"kind": "para", "text": f(s1["restricted_use"]["text"])},
          {"kind": "signature", "lines": [model, "AI Auditor", report_date, "Not an official SOC 2 audit."]}]
    section1 = {"title": f(s1["title"]), "blocks": b}

    # Section II. A draft description is not a management assertion and must
    # not be rendered as though management signed one.
    s2 = text["section2"]
    sys_ = privacy.report_system(eng)
    if sys_ and sys_.get("status") == "management-approved":
        items = [s2["items"]["description"], s2["items"]["design"]] + ([s2["items"]["operating"]] if t2 else [])
        if not t2:
            items[-1] = items[-1].rstrip(";") + "."
        section2 = {"title": f(s2["title"]), "blocks": [
            {"kind": "para", "text": f(s2["intro"])}, {"kind": "para", "text": f(s2["confirm"])},
            {"kind": "list", "items": [f(x) for x in items], "enum": True},
            {"kind": "signature", "lines": [mgmt_name, mgmt_title, report_date]}]}
    else:
        section2 = {"title": f(s2["title"]) + " — Pending Management Approval", "blocks": [
            {"kind": "para", "text": "Management has not approved the system description or supplied a signed assertion for this provisional AI assessment. No management assertion is made in this section."}]}

    # Section III. A compliance-system draft is evidence, not the description readers see.
    s3 = text["section3"]
    blocks = []
    if not sys_:
        blocks.append({"kind": "para", "text": f(s3["omitted"])})
    elif sys_.get("status") != "management-approved":
        blocks.append({"kind": "para", "text": f(s3["unapproved"])})
    for key, heading in s3["headings"].items():
        if not sys_:
            break
        value = sys_.get(key)
        if not value:
            continue
        blocks.append({"kind": "heading", "text": f(heading)})
        if key == "components" and isinstance(value, dict):
            for comp, comp_text in value.items():
                if comp_text:
                    blocks.append({"kind": "heading", "text": s3["component_names"].get(comp, comp.title()), "level": 3})
                    blocks += _prose(comp_text)
        else:
            blocks += _prose(value)
    section3 = {"title": f(s3["title"]), "blocks": blocks}

    # Section IV
    s4 = text["section4"]
    workpapers = eng.load_workpapers()
    by_crit = {}
    for cid, wp in sorted(workpapers.items()):
        for c in wp["criteria"]:
            by_crit.setdefault(c, []).append(wp)
    groups = []
    for crit in eng.criteria:
        code = crit["id"].split(".")[0]
        if not groups or groups[-1]["code"] != code:
            groups.append({"code": code, "title": f"{code}: {crit['group']}", "criteria": []})
        rows = [_row(eng, wp, s4, v, t2) for wp in by_crit.get(crit["id"], [])]
        groups[-1]["criteria"].append({"id": crit["id"], "text": crit.get("text") or crit["summary"], "rows": rows})
    section4 = {"title": f(s4["title"]), "intro": [f(s4["intro"]["type2" if t2 else "type1"])] + ([f(s4["methods"])] if t2 else []),
                "columns": s4["columns"] if t2 else s4["columns_type1"], "groups": groups}

    # Section V
    s5 = text["section5"]
    responses = [{"control": wp["control_id"], "exception": x["description"], "response": x["management_response"]}
                 for wp in workpapers.values() for x in wp["exceptions"] if x.get("management_response")]
    section5 = {"title": f(s5["title"]), "intro": f(s5["intro"]), "responses": responses, "none": s5["none"]}

    cover = text["cover"]
    return {
        "final": final,
        "org": cfg["service_organization"], "system": cfg["system"], "auditor": "AI Audit",
        "model": model,
        "signer_name": model,
        "signer_title": "AI Auditor",
        "report_date": report_date,
        "disclaimer": f(cover["disclaimer"]),
        "report_type": eng.report_type, "period": f(v["period_dates"]),
        "title": f(cover["title"]), "restricted": f(cover["restricted"]),
        "generated": dt.date.today().isoformat(),
        "sections": [section1, section2, section3], "section4": section4, "section5": section5,
    }


LIST_LABELS = {"csocs": "Complementary subservice organization controls assumed in the design of our controls:"}


def _prose(value) -> list[dict]:
    """Turn a system.yaml value (text, list of text, or list of named entries) into report blocks."""
    if isinstance(value, str):
        return [{"kind": "para", "text": " ".join(p.split())} for p in value.split("\n\n") if p.strip()]
    if isinstance(value, list) and all(isinstance(x, dict) for x in value):
        blocks = []
        for x in value:
            blocks.append({"kind": "heading", "text": x.get("name") or x.get("title") or "", "level": 3})
            for k, v in x.items():
                if k in ("name", "title") or not v:
                    continue
                if isinstance(v, list):
                    blocks += [{"kind": "para", "text": LIST_LABELS.get(k, k.replace("_", " ").capitalize() + ":")}, {"kind": "list", "items": [str(i) for i in v]}]
                else:
                    blocks.append({"kind": "para", "text": str(v)})
        return blocks
    if isinstance(value, list):
        return [{"kind": "list", "items": [str(x) for x in value]}]
    return [{"kind": "para", "text": str(value)}]


def _row(eng: Engagement, wp: dict, s4: dict, v: _Keep, t2: bool) -> dict:
    row = {"control": wp["control_id"], "activity": privacy.activity(eng, wp)}
    if not t2:
        return row
    tests = [p["text"] for p in wp["procedures"]]
    plan = wp["plan"]
    if plan["population"] and plan["population"]["size"] > 1:
        tests.append(f"Sample of {plan['sample_size']} selected from a population of {plan['population']['size']}.")
    concl = wp["conclusion"]
    if concl == "no-exceptions":
        result = s4["no_exceptions"]
    elif concl == "not-tested":
        result = _fill(s4["not_tested"], _Keep(v, reason=wp.get("scope_limitation") or ""))
    elif concl == "design-deficiency":
        result = _fill(s4["design_deficiency"], _Keep(v, reason=wp["design"]["rationale"]))
    else:
        result = " ".join(x["description"] for x in wp["exceptions"])
    row.update(tests=tests, result=result, exception=concl != "no-exceptions")
    return row


# --- PDF -------------------------------------------------------------------------


def _compile_pdf(data: dict, out: Path) -> None:
    try:
        import typst
    except ImportError as e:
        raise AuditError("The `typst` Python package is required: pip install -r scripts/requirements.txt") from e
    with tempfile.TemporaryDirectory() as tmp:
        shutil.copyfile(ASSETS / "report" / "report.typ", Path(tmp) / "report.typ")
        shutil.copyfile(ASSETS / "report" / "logo.svg", Path(tmp) / "logo.svg")
        dump_json(data, Path(tmp) / "data.json")
        typst.compile(str(Path(tmp) / "report.typ"), output=str(out))


# --- spreadsheet and index -----------------------------------------------------------


def _write_xlsx(eng: Engagement, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = "Controls"
    ws.append(["Control", "Criteria", "Frequency", "Nature", "Population", "Sample", "Design effective", "Conclusion",
               "Exceptions", "Confidence", "Prepared by", "Control activity"])
    samples = wb.create_sheet("Samples")
    samples.append(["Control", "Item", "Results", "Evidence", "Note"])
    exc = wb.create_sheet("Exceptions")
    exc.append(["Control", "Item", "Description", "Evidence", "Management response"])
    for cid, wp in sorted(eng.load_workpapers().items()):
        p = wp["plan"]
        ws.append([cid, " ".join(wp["criteria"]), p["frequency"], p["nature"],
                   f"{p['population']['source']} ({p['population']['size']})" if p["population"] else "",
                   p["sample_size"], wp["design"]["effective"], wp["conclusion"], len(wp["exceptions"]),
                   wp.get("confidence"), wp.get("prepared_by"), privacy.activity(eng, wp)])
        for item in wp["items"]:
            samples.append([cid, item["id"], ", ".join(f"{k}={r}" for k, r in sorted(item["results"].items())),
                            " ".join(item["evidence"]), item.get("note", "")])
        for x in wp["exceptions"]:
            exc.append([cid, x["item"], x["description"], " ".join(x["evidence"]), x.get("management_response") or ""])
    ev = wb.create_sheet("Evidence")
    ev.append(["ID", "Title", "Kind", "Path", "SHA-256", "Obtained", "Date", "Controls"])
    for a in eng.manifest["artifacts"]:
        ev.append([a["id"], privacy.redact(a["title"], eng), a["kind"], privacy.redact(a["path"], eng), a["sha256"], a["obtained"], a.get("date", ""), " ".join(a.get("controls", []))])
    for sheet in wb.worksheets:
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        sheet.freeze_panes = "A2"
    wb.save(path)


def _write_evidence_index(eng: Engagement, path: Path) -> None:
    cited = {}
    for cid, wp in eng.load_workpapers().items():
        ids = set(wp["design"]["evidence"]) | {e for i in wp["items"] for e in i["evidence"]} | {e for x in wp["exceptions"] for e in x["evidence"]}
        if wp.get("population_check"):
            ids |= set(wp["population_check"]["evidence"])
        for e in ids:
            cited.setdefault(e, []).append(cid)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "title", "kind", "path", "sha256", "obtained", "date", "cited_by"])
        for a in eng.manifest["artifacts"]:
            w.writerow([a["id"], privacy.redact(a["title"], eng), a["kind"], privacy.redact(a["path"], eng), a["sha256"], a["obtained"], a.get("date", ""), " ".join(sorted(cited.get(a["id"], [])))])
