"""Drata connector: pull a SOC 2 evidence bundle through the Drata public API (v2).

Drata model -> bundle:
  Workspace controls + SOC 2 requirements   -> controls.csv, criteria from requirement names
  Evidence library (current versions)       -> evidence artifacts, linked by control
  Personnel (startedAt / separatedAt)       -> hires and terminations populations
  Monitoring tests                          -> evidence export (current state only)

Options (engagement.yaml source.options):
  workspace_id  optional when the account has one workspace
  api_url       default https://public-api.drata.com (EU: public-api.eu.drata.com, APAC: public-api.apac.drata.com)
Environment:
  DRATA_API_KEY   API key with read access
"""

from __future__ import annotations

import json
import os
import urllib.parse

from core import AuditError, parse_date

from .base import BundleWriter, find_criteria, slug

PAGE_SIZE = 200  # API allows up to 500; 200 keeps responses small with large evidence expansions.


def pull(writer: BundleWriter, options: dict, engagement) -> None:
    api = options.get("api_url", "https://public-api.drata.com").rstrip("/") + "/public/v2"
    key = os.environ.get("DRATA_API_KEY")
    if not key:
        raise AuditError("Set DRATA_API_KEY to a Drata API key with read access.")
    headers = {"Authorization": f"Bearer {key}"}

    def pages(path: str, **params):
        cursor = None
        while True:
            query = [("size", PAGE_SIZE)] + [(k, v) for k, vs in params.items() for v in (vs if isinstance(vs, list) else [vs])]
            if cursor:
                query.append(("cursor", cursor))
            data, _ = writer.http_json(f"{api}{path}?{urllib.parse.urlencode(query)}", headers=headers)
            yield from (data or {}).get("data", [])
            cursor = ((data or {}).get("pagination") or {}).get("cursor")
            if not cursor:
                return

    ws = options.get("workspace_id")
    if not ws:
        workspaces = list(pages("/workspaces"))
        if len(workspaces) != 1:
            raise AuditError(f"Set source.options.workspace_id; the account has {len(workspaces)} workspaces: "
                             + ", ".join(f"{w['id']} ({w.get('name')})" for w in workspaces))
        ws = workspaces[0]["id"]
    writer.source = f"{api} workspace {ws}"
    start, end = engagement.period

    rows, by_drata_id = [], {}
    for c in pages(f"/workspaces/{ws}/controls", isArchived="false"):
        criteria = find_criteria(c.get("requirements"))
        if not criteria:
            reqs = list(pages(f"/workspaces/{ws}/controls/{c['id']}/requirements", frameworkTag="SOC_2"))
            criteria = find_criteria([r.get("name") for r in reqs], [r.get("externalId") for r in reqs])
        cid = c.get("code") or f"DC-{c['id']}"
        by_drata_id[c["id"]] = cid
        rows.append({"id": cid, "title": c.get("name", ""), "description": c.get("description") or c.get("name", ""),
                     "criteria": criteria, "source_ref": f"drata:control/{c['id']}"})

    hires, terms = [], []
    for p in pages("/personnel", **{"expand[]": ["user"]}):
        s, e = parse_date(p.get("startedAt")), parse_date(p.get("separatedAt"))
        user = p.get("user") or {}
        row = {"name": f"{user.get('firstName', '')} {user.get('lastName', '')}".strip(), "email": user.get("email", ""), "status": p.get("employmentStatus", "")}
        if s and start <= s <= end:
            hires.append({"id": f"H-{p['id']}", "date": s.isoformat(), **row})
        if e and start <= e <= end:
            terms.append({"id": f"T-{p['id']}", "date": e.isoformat(), **row})
    pop_hires = writer.add_population("hires", hires, title="New hires in period (Drata personnel)", source_ref="drata:personnel")
    pop_terms = writer.add_population("terminations", terms, title="Terminations in period (Drata personnel)", source_ref="drata:personnel")
    for row in rows:
        text = (row["title"] + " " + row["description"]).lower()
        if any(k in text for k in ("terminat", "offboard", "deprovision")):
            row["population"] = pop_terms
        elif any(k in text for k in ("onboard", "new hire", "background check")):
            row["population"] = pop_hires
    writer.set_controls(rows)
    writer.warn("Drata does not provide a system description; management must supply bundle/system.yaml")

    for item in pages(f"/workspaces/{ws}/evidence-library", **{"expand[]": ["versions", "controls"]}):
        controls = [by_drata_id[c["id"]] for c in item.get("controls") or [] if c.get("id") in by_drata_id]
        current = [v for v in item.get("versions") or [] if v.get("current")]
        for v in current:
            detail, _ = writer.http_json(f"{api}/workspaces/{ws}/evidence-library/{item['id']}/versions/{v['id']}", headers=headers)
            url = (detail or {}).get("downloadUrl")
            if not url:
                writer.warn(f"evidence '{item.get('name')}' version {v['id']} has no download URL")
                continue
            name = os.path.basename(urllib.parse.urlparse(url).path) or f"{slug(item.get('name', 'evidence'))}.bin"
            writer.add_download(url, name, title=item.get("name") or f"Evidence {item['id']}", controls=controls,
                                date=(detail.get("filedAt") or detail.get("createdAt") or "")[:10] or None,
                                obtained="direct", source_ref=f"drata:evidence-library/{item['id']}")

    try:
        tests = list(pages(f"/workspaces/{ws}/monitoring-tests"))
        writer.add_bytes(json.dumps(tests, indent=2), "monitoring-tests.json",
                         title="Drata monitoring tests (current state at pull time, not period history)", source_ref="drata:monitoring-tests")
    except AuditError as e:
        writer.warn(f"monitoring tests: {e}")
