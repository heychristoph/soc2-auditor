"""Probo connector: pull a SOC 2 evidence bundle from Probo (probo.com or self-hosted).

Probo exposes every entity through its MCP API. This connector speaks that API
directly over HTTP (JSON-RPC), so it runs from any agent or from a plain shell,
with or without MCP support in the agent.

Probo model -> bundle:
  Framework "SOC 2" controls (e.g. CC6.1)  -> criteria
  Measures (what the org implemented)       -> controls.csv rows, criteria via control links
  Measure evidences (files and links)       -> evidence artifacts
  Documents (policies, latest version)      -> policy artifacts
  People (contract start / end)             -> hires and terminations populations
  Third parties                             -> vendors population
  Risks, access review campaigns            -> evidence exports (JSON)
  Organization context                      -> draft system.yaml for management

Options (engagement.yaml source.options):
  url              Probo instance root, default https://us.probo.com
  organization_id  required
  framework_id     optional; defaults to the framework whose name contains "SOC 2"
Environment:
  PROBO_TOKEN      OAuth access token with read scopes
"""

from __future__ import annotations

import itertools
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from core import AuditError, parse_date

from .base import BundleWriter, find_criteria, slug

PAGE_SIZE = 100  # Largest page the API accepts; keeps request count low for big orgs.


class ProboMCP:
    """Minimal MCP-over-HTTP client: initialize once, then call tools."""

    def __init__(self, base_url: str, token: str):
        self.url = base_url.rstrip("/") + "/api/mcp/v1"
        self.token = token
        self.session_id = None
        self._ids = itertools.count(1)
        self._rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "soc2-audit", "version": "1"}})
        self._rpc("notifications/initialized", None, notify=True)

    def call(self, tool: str, **arguments) -> dict:
        result = self._rpc("tools/call", {"name": tool, "arguments": arguments})
        if result.get("isError"):
            text = " ".join(c.get("text", "") for c in result.get("content", []))
            raise AuditError(f"Probo tool {tool} failed: {text[:300]}")
        if isinstance(result.get("structuredContent"), dict):
            return result["structuredContent"]
        for content in result.get("content", []):
            if content.get("type") == "text":
                return json.loads(content["text"])
        return {}

    def pages(self, tool: str, key: str, **arguments):
        """Yield every item across cursor-paginated results."""
        cursor = None
        while True:
            args = dict(arguments, size=PAGE_SIZE)
            if cursor:
                args["cursor"] = cursor
            out = self.call(tool, **args)
            yield from out.get(key) or []
            cursor = out.get("next_cursor")
            if not cursor:
                return

    def _rpc(self, method: str, params, notify: bool = False):
        body = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = next(self._ids)
        if params is not None:
            body["params"] = params
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {self.token}",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                self.session_id = resp.headers.get("Mcp-Session-Id") or self.session_id
                raw = resp.read().decode()
                ctype = resp.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            raise AuditError(f"Probo MCP {method} failed with HTTP {e.code}: {e.read().decode(errors='replace')[:300]}") from e
        if notify:
            return None
        if "text/event-stream" in ctype:
            messages = [json.loads(line[5:]) for line in raw.splitlines() if line.startswith("data:")]
            reply = next((m for m in messages if m.get("id") == body["id"]), messages[-1] if messages else {})
        else:
            reply = json.loads(raw)
        if reply.get("error"):
            raise AuditError(f"Probo MCP {method} error: {reply['error'].get('message')}")
        return reply.get("result", {})


def pull(writer: BundleWriter, options: dict, engagement) -> None:
    base = options.get("url", "https://us.probo.com").rstrip("/")
    org = options.get("organization_id")
    token = os.environ.get("PROBO_TOKEN")
    if not org:
        raise AuditError("Probo connector needs source.options.organization_id in engagement.yaml.")
    if not token:
        raise AuditError("Set PROBO_TOKEN to a Probo OAuth access token with read scopes.")
    writer.source = f"{base} organization {org}"
    api = ProboMCP(base, token)
    start, end = engagement.period

    # 1. Framework and its requirements (criteria).
    framework_id = options.get("framework_id")
    if not framework_id:
        frameworks = list(api.pages("listFrameworks", "frameworks", organization_id=org))
        soc2 = [f for f in frameworks if "soc 2" in f["name"].lower() or "soc2" in f["name"].lower()]
        if not soc2:
            names = ", ".join(f["name"] for f in frameworks) or "none"
            raise AuditError(f"No SOC 2 framework found in Probo (frameworks: {names}). Set source.options.framework_id.")
        framework_id = soc2[0]["id"]
    requirements = list(api.pages("listControls", "controls", organization_id=org, filter={"framework_id": framework_id}))

    # 2. Measures are the organization's controls; criteria come from the requirements they link to.
    measures: dict[str, dict] = {}
    measure_criteria: dict[str, list[str]] = {}
    requirement_measures: dict[str, list[str]] = {}
    for req in requirements:
        criteria = find_criteria(req.get("section_title"), req.get("name"))
        if not criteria:
            writer.warn(f"framework control '{req.get('section_title')} {req.get('name')}' has no recognizable criterion ID")
        for m in api.pages("listControlMeasures", "measures", control_id=req["id"]):
            measures[m["id"]] = m
            measure_criteria.setdefault(m["id"], [])
            requirement_measures.setdefault(req["id"], []).append(m["id"])
            for c in criteria:
                if c not in measure_criteria[m["id"]]:
                    measure_criteria[m["id"]].append(c)

    ordered = sorted(measures.values(), key=lambda m: (m.get("category") or "", m["name"]))
    control_id = {m["id"]: f"M-{i:03d}" for i, m in enumerate(ordered, 1)}
    rows = []
    for m in ordered:
        if m.get("state") == "NOT_APPLICABLE":
            writer.warn(f"measure '{m['name']}' is marked not applicable in Probo and is excluded")
            continue
        if m.get("state") not in ("IMPLEMENTED", None):
            writer.warn(f"measure '{m['name']}' has state {m.get('state')} in Probo")
        rows.append({
            "id": control_id[m["id"]],
            "title": m["name"],
            "description": m.get("description") or m["name"],
            "criteria": measure_criteria.get(m["id"], []),
            "source_ref": f"probo:measure/{m['id']}",
        })

    # 3. Populations from people and third parties.
    people = list(api.pages("listUsers", "users", organization_id=org))
    hires, terms = [], []
    for p in people:
        contract = p.get("contract") or {}
        s, e = parse_date(contract.get("start")), parse_date(contract.get("end"))
        base_row = {"name": p.get("full_name", ""), "email": p.get("email_address", ""), "position": p.get("position") or "", "state": p.get("state", "")}
        if s and start <= s <= end:
            hires.append({"id": f"H-{slug(p['id'])[-8:]}", "date": s.isoformat(), **base_row})
        if e and start <= e <= end:
            terms.append({"id": f"T-{slug(p['id'])[-8:]}", "date": e.isoformat(), **base_row})
    pop_hires = writer.add_population("hires", hires, title="New hires in period (Probo people, contract start)", source_ref="probo:listUsers")
    pop_terms = writer.add_population("terminations", terms, title="Terminations in period (Probo people, contract end)", source_ref="probo:listUsers")
    writer.add_bytes(json.dumps(people, indent=2), "people.json", title="Probo people export (all)", source_ref="probo:listUsers")

    vendors = list(api.pages("listThirdParties", "thirdParties", organization_id=org))
    writer.add_population(
        "vendors",
        [{"id": f"V-{slug(v['id'])[-8:]}", "date": (v.get("created_at") or "")[:10], "name": v["name"], "category": v.get("category") or ""} for v in vendors if v.get("created_at")],
        title="Third parties (Probo)",
        source_ref="probo:listThirdParties",
    )

    # Link populations to controls by keyword; the auditor confirms in testplan.csv.
    for row in rows:
        text = (row["title"] + " " + row["description"]).lower()
        if any(k in text for k in ("terminat", "offboard", "deprovision")):
            row["population"] = pop_terms
        elif any(k in text for k in ("onboard", "new hire", "background check")):
            row["population"] = pop_hires
    writer.set_controls(rows)

    # 4. Evidence attached to measures.
    for m in ordered:
        cid = control_id[m["id"]]
        for ev in api.pages("listMeasureEvidences", "evidences", measure_id=m["id"]):
            if ev.get("state") != "FULFILLED":
                writer.warn(f"{cid}: evidence '{ev.get('description') or ev['id']}' is still requested, not provided")
                continue
            title = ev.get("description") or ev.get("reference_id") or ev["id"]
            date = (ev.get("created_at") or "")[:10] or None
            ref = f"probo:evidence/{ev['id']}"
            if ev.get("type") == "LINK":
                writer.add_bytes(f"[InternetShortcut]\nURL={ev['url']}\n", f"{slug(title)}.url", title=title, controls=[cid], date=date, obtained="client", source_ref=ref)
                continue
            url = urllib.parse.urljoin(base + "/", ev["url"])
            name = os.path.basename(urllib.parse.urlparse(url).path) or f"{slug(title)}.bin"
            headers = {"Authorization": f"Bearer {token}"} if url.startswith(base) else None
            writer.add_download(url, name, title=title, headers=headers, controls=[cid], date=date, obtained="direct", source_ref=ref)

    # 5. Policies: latest published version of each document linked to a requirement.
    seen_docs = set()
    for req in requirements:
        linked = [control_id[mid] for mid in requirement_measures.get(req["id"], [])]
        for doc in api.pages("listControlDocuments", "documents", control_id=req["id"]):
            if doc["id"] in seen_docs:
                continue
            seen_docs.add(doc["id"])
            versions = list(api.pages("listDocumentVersions", "document_versions", document_id=doc["id"]))
            published = [v for v in versions if v.get("status") == "PUBLISHED"] or versions
            if not published:
                continue
            latest = max(published, key=lambda v: (v.get("major", 0), v.get("minor", 0)))
            full = api.call("getDocumentVersion", id=latest["id"]).get("document_version", latest)
            body = f"# {full.get('title', 'Document')}\n\nVersion {full.get('major')}.{full.get('minor')}, published {full.get('published_at') or 'n/a'}\n\n{full.get('content') or ''}"
            writer.add_bytes(body, f"{slug(full.get('title', doc['id']))}.md", title=f"Policy: {full.get('title')}", kind="policy",
                             controls=linked, date=(full.get("published_at") or "")[:10] or None, obtained="direct", source_ref=f"probo:document/{doc['id']}")

    # 6. Registers useful for risk assessment and access review controls.
    for tool, key, title in (("listRisks", "risks", "Risk register (Probo)"), ("listAccessReviewCampaigns", "campaigns", "Access review campaigns (Probo)")):
        try:
            items = list(api.pages(tool, key, organization_id=org))
        except AuditError as e:
            writer.warn(f"{tool}: {e}")
            continue
        writer.add_bytes(json.dumps(items, indent=2), f"{slug(title)}.json", title=title, source_ref=f"probo:{tool}")

    # 7. Draft system description from the organization context. Management must review it.
    try:
        ctx = api.call("getOrganizationContext", organization_id=org).get("organization_context") or {}
    except AuditError as e:
        writer.warn(f"getOrganizationContext: {e}")
        ctx = {}
    writer.set_system({
        "status": "draft",
        "overview": ctx.get("product") or "",
        "services": ctx.get("customers") or "",
        "commitments": [],
        "components": {
            "infrastructure": ctx.get("architecture") or "",
            "software": "",
            "people": ctx.get("team") or "",
            "procedures": ctx.get("processes") or "",
            "data": "",
        },
        "subservice_organizations": [],
        "cuecs": [],
        "incidents": "",
        "changes": "",
    }, obtained="direct")
