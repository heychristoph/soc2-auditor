"""Vanta connector: pull an audit's evidence through the Vanta Auditor API.

For audit firms registered as Vanta audit partners. The firm's application
authenticates with client credentials and sees only audits assigned to the firm.

Vanta model -> bundle:
  Audit controls (with framework sections)   -> controls.csv, criteria from sections
  Audit evidence + download URLs             -> evidence artifacts, linked by related controls
  In-scope people (start / end dates)        -> hires and terminations populations
  Code changes                               -> changes population

Options (engagement.yaml source.options):
  audit_id   optional when the firm has exactly one active audit
  api_url    default https://api.vanta.com (use https://api.vanta-gov.com for Vanta Gov)
Environment:
  VANTA_CLIENT_ID, VANTA_CLIENT_SECRET   Auditor API application credentials
"""

from __future__ import annotations

import os
import urllib.parse

from core import AuditError, parse_date

from .base import BundleWriter, find_criteria, slug

PAGE_SIZE = 100  # API maximum per page.
SCOPES = "auditor-api.audit:read auditor-api.auditor:read"


def pull(writer: BundleWriter, options: dict, engagement) -> None:
    api = options.get("api_url", "https://api.vanta.com").rstrip("/")
    client_id, secret = os.environ.get("VANTA_CLIENT_ID"), os.environ.get("VANTA_CLIENT_SECRET")
    if not client_id or not secret:
        raise AuditError("Set VANTA_CLIENT_ID and VANTA_CLIENT_SECRET (Auditor API application credentials).")
    token, _ = writer.http_json(f"{api}/oauth/token", method="POST", body={
        "client_id": client_id, "client_secret": secret, "scope": SCOPES, "grant_type": "client_credentials",
    })
    headers = {"Authorization": f"Bearer {token['access_token']}"}

    def pages(path: str, **params):
        cursor = None
        while True:
            query = dict(params, pageSize=PAGE_SIZE)
            if cursor:
                query["pageCursor"] = cursor
            data, _ = writer.http_json(f"{api}/v1{path}?{urllib.parse.urlencode(query)}", headers=headers)
            results = (data or {}).get("results", {})
            yield from results.get("data", [])
            info = results.get("pageInfo", {})
            if not info.get("hasNextPage"):
                return
            cursor = info.get("endCursor")

    audit_id = options.get("audit_id")
    if not audit_id:
        audits = list(pages("/audits"))
        if len(audits) != 1:
            listing = ", ".join(f"{a.get('id')} ({a.get('customerDisplayName') or a.get('displayName', '')})" for a in audits) or "none"
            raise AuditError(f"Set source.options.audit_id; the firm can see {len(audits)} audits: {listing}")
        audit_id = audits[0]["id"]
    writer.source = f"{api} audit {audit_id}"
    start, end = engagement.period

    # Controls
    rows, by_name = [], {}
    for c in pages(f"/audits/{audit_id}/controls"):
        cid = c.get("externalId") or c["id"]
        by_name[c.get("name", "")] = cid
        owner = (c.get("owner") or {}).get("displayName", "") if isinstance(c.get("owner"), dict) else ""
        rows.append({
            "id": cid, "title": c.get("name", ""), "description": c.get("description") or c.get("name", ""),
            "criteria": find_criteria(c.get("sections"), c.get("domains")), "owner": owner, "source_ref": f"vanta:control/{c['id']}",
        })

    # Populations
    hires, terms = [], []
    for p in pages(f"/audits/{audit_id}/personnel/people"):
        s, e = parse_date(p.get("startDate")), parse_date(p.get("endDate"))
        row = {"name": p.get("name", ""), "email": p.get("email", ""), "job_title": p.get("jobTitle") or "", "status": str(p.get("employmentStatus") or "")}
        if s and start <= s <= end:
            hires.append({"id": f"H-{slug(p['id'])[-8:]}", "date": s.isoformat(), **row})
        if e and start <= e <= end:
            terms.append({"id": f"T-{slug(p['id'])[-8:]}", "date": e.isoformat(), **row})
    pop_hires = writer.add_population("hires", hires, title="New hires in period (Vanta people)", source_ref="vanta:personnel/people")
    pop_terms = writer.add_population("terminations", terms, title="Terminations in period (Vanta people)", source_ref="vanta:personnel/people")

    changes = []
    try:
        for ch in pages(f"/audits/{audit_id}/assets/code-changes"):
            code = ch.get("codeChange") or {}
            closed = parse_date(code.get("closedAt"))
            if closed and start <= closed <= end:
                changes.append({"id": f"CH-{slug(ch['id'])[-8:]}", "date": closed.isoformat(), "identifier": code.get("identifier", ""),
                                "repository": code.get("repository", ""), "service": code.get("service", "")})
    except AuditError as e:
        writer.warn(f"code changes: {e}")
    pop_changes = writer.add_population("changes", changes, title="Code changes closed in period (Vanta)", source_ref="vanta:assets/code-changes")

    for row in rows:
        text = (row["title"] + " " + row["description"]).lower()
        if any(k in text for k in ("terminat", "offboard", "deprovision")):
            row["population"] = pop_terms
        elif any(k in text for k in ("onboard", "new hire", "background check")):
            row["population"] = pop_hires
        elif any(k in text for k in ("change", "pull request", "deploy")):
            row["population"] = pop_changes
    writer.set_controls(rows)
    writer.warn("Vanta does not provide a system description; management must supply bundle/system.yaml")

    # Evidence
    for ev in pages(f"/audits/{audit_id}/evidence"):
        if ev.get("deletionDate"):
            continue
        controls = [by_name[rc["name"]] for rc in ev.get("relatedControls") or [] if rc.get("name") in by_name]
        title = ev.get("name") or ev["id"]
        date = (ev.get("statusUpdatedDate") or ev.get("creationDate") or "")[:10] or None
        for u in pages(f"/audits/{audit_id}/evidence/{ev['id']}/urls"):
            if not u.get("isDownloadable", True):
                writer.warn(f"evidence '{title}' file {u.get('filename')} is not downloadable")
                continue
            writer.add_download(u["url"], u.get("filename") or f"{slug(title)}.bin", title=title, controls=controls,
                                date=date, obtained="direct", source_ref=f"vanta:evidence/{ev['id']}")
