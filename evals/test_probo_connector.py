#!/usr/bin/env python3
"""Exercise the Probo connector against a local mock of Probo's MCP API.

    python evals/test_probo_connector.py

The mock serves the type2 fixture in Probo's shapes (framework controls,
measures, evidences, documents, people, third parties) using the tool names and
fields from Probo's published MCP specification, then runs ingest, check, plan
and sample through the real CLI.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "soc2-audit" / "scripts"))

from core import dump_yaml, load_criteria, load_yaml, read_csv  # noqa: E402

TOKEN = "test-token"


def build_state(export: Path) -> dict:
    controls = read_csv(export / "controls.csv")
    summaries = {c["id"]: c["summary"] for c in load_criteria()}
    criteria = sorted({x for c in controls for x in c["criteria"].split()})
    meta = {m["path"]: m for m in read_csv(export / "evidence.csv")}
    ts = "2026-03-01T00:00:00Z"
    state = {
        "requirements": [{"id": f"ctl_{x}", "section_title": x, "name": summaries[x]} for x in criteria],
        "measures": {c["id"]: {"id": f"msr_{c['id']}", "name": c["title"], "description": c["description"], "category": "", "state": "IMPLEMENTED",
                               "created_at": ts, "updated_at": ts} for c in controls},
        "req_measures": {x: [c["id"] for c in controls if x in c["criteria"].split()] for x in criteria},
        "evidences": {c["id"]: [] for c in controls},
        "files": {},
        "documents": {},
    }
    for path in sorted((export / "evidence").rglob("*")):
        if path.is_file():
            cid = path.parent.name
            fid = f"file_{len(state['files'])}"
            state["files"][f"/files/{fid}/{path.name}"] = path.read_bytes()
            state["evidences"][cid].append({"id": f"evd_{fid}", "organization_id": "org_1", "measure_id": f"msr_{cid}", "state": "FULFILLED",
                                            "reference_id": path.name, "type": "FILE", "url": f"/files/{fid}/{path.name}", "description": path.stem,
                                            "created_at": ts, "updated_at": ts})
    for path in sorted((export / "policies").glob("*.md")):
        m = meta[f"policies/{path.name}"]
        doc = {"id": f"doc_{path.stem}", "controls": m["controls"].split(), "framework_controls": [],
               "title": m["title"].replace("Policy: ", ""), "content": path.read_text()}
        state["documents"][doc["id"]] = doc
    # One policy hangs off the framework control itself. The other twelve hang off measures only.
    state["documents"]["doc_control_only"] = {
        "id": "doc_control_only", "controls": [], "framework_controls": [f"ctl_{criteria[0]}"],
        "title": "Control linked only", "content": "Direct framework-control link.",
    }
    pops = {n: read_csv(export / "populations" / f"{n}.csv") for n in ("hires", "terminations", "vendors")}
    state["users"] = ([{"id": f"usr_{h['id']}", "full_name": h["name"], "email_address": "", "state": "ACTIVE", "contract": {"start": h["date"], "end": None}} for h in pops["hires"]]
                      + [{"id": f"usr_{t['id']}", "full_name": t["name"], "email_address": "", "state": "DEACTIVATED", "contract": {"start": "2023-01-09", "end": t["date"]}} for t in pops["terminations"]])
    state["vendors"] = [{"id": f"tp_{v['id']}", "name": v["name"], "category": v["category"], "created_at": v["date"] + "T00:00:00Z"} for v in pops["vendors"]]
    state["context"] = load_yaml(export / "system.yaml")
    # Probo's MCP list leaves url empty for uploaded files. The file is only on the console GraphQL API.
    first = next(iter(state["evidences"]))
    state["files"]["/files/hidden/mfa-screenshot.png"] = b"PNG-MFA-SCREENSHOT"
    state["evidences"][first].append({
        "id": "evd_hidden", "organization_id": "org_1", "measure_id": f"msr_{first}", "state": "FULFILLED",
        "reference_id": "mfa-screenshot.png", "type": "FILE", "url": "", "description": "MFA screenshot",
        "created_at": ts, "updated_at": ts,
    })
    return state


def call_tool(state: dict, name: str, args: dict) -> dict:
    req_by_id = {r["id"]: r for r in state["requirements"]}
    if name == "listFrameworks":
        return {"frameworks": [{"id": "fw_soc2", "organization_id": "org_1", "name": "SOC 2"}]}
    if name == "listControls":
        return {"controls": state["requirements"]}
    if name == "listControlMeasures":
        crit = req_by_id[args["control_id"]]["section_title"]
        return {"measures": [state["measures"][cid] for cid in state["req_measures"][crit]]}
    if name == "listMeasureEvidences":
        return {"evidences": state["evidences"][args["measure_id"].removeprefix("msr_")]}
    if name == "listControlDocuments":
        return {"documents": [{"id": d["id"]} for d in state["documents"].values() if args["control_id"] in d.get("framework_controls", [])]}
    if name == "listMeasureDocuments":
        cid = args["measure_id"].removeprefix("msr_")
        return {"documents": [{"id": d["id"]} for d in state["documents"].values() if cid in d["controls"]]}
    if name == "listDocumentVersions":
        d = state["documents"][args["document_id"]]
        return {"document_versions": [{"id": f"ver_{d['id']}", "status": "PUBLISHED", "major": 4, "minor": 2, "title": d["title"]}]}
    if name == "getDocumentVersion":
        d = state["documents"][args["id"].removeprefix("ver_")]
        return {"document_version": {"id": args["id"], "title": d["title"], "major": 4, "minor": 2, "status": "PUBLISHED", "content": d["content"], "published_at": "2026-01-15T00:00:00Z"}}
    if name == "listDocumentVersionSignatures":
        doc_id = args["document_version_id"].removeprefix("ver_")
        signer = state["users"][0]["id"]
        return {"document_version_signatures": [{"id": f"sig_{doc_id}", "document_version_id": args["document_version_id"],
                                                 "state": "SIGNED", "signed_by": signer, "signed_at": "2026-09-28T12:00:00Z"}]}
    if name == "listDocumentVersionApprovalQuorums":
        return {"approval_quorums": [{"id": "quorum_1", "status": "APPROVED", "version_id": args["document_version_id"]}]}
    if name == "listDocumentVersionApprovalDecisions":
        signer = state["users"][0]["id"]
        return {"approval_decisions": [{"id": "dec_1", "approver_id": signer, "state": "APPROVED", "decided_at": "2026-09-28T12:00:00Z"}]}
    if name == "listAccessEntries":
        return {"access_entries": []}
    if name == "listUsers":
        return {"users": state["users"]}
    if name == "listThirdParties":
        return {"thirdParties": state["vendors"]}
    if name == "listRisks":
        return {"risks": []}
    if name == "listAccessReviewCampaigns":
        return {"campaigns": []}
    if name == "getOrganizationContext":
        c = state["context"]
        return {"organization_context": {"product": c["overview"], "customers": c["services"], "architecture": c["components"]["infrastructure"],
                                         "team": c["components"]["people"], "processes": c["components"]["procedures"]}}
    raise KeyError(name)


def serve(state: dict) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _auth(self) -> bool:
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                self.send_response(401)
                self.end_headers()
                return False
            return True

        def do_GET(self):
            if not self._auth():
                return
            body = state["files"].get(self.path)
            self.send_response(200 if body is not None else 404)
            self.end_headers()
            self.wfile.write(body or b"")

        def do_POST(self):
            if not self._auth():
                return
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.startswith("/api/console/v1/graphql"):
                found = req.get("variables", {}).get("id") == "evd_hidden"
                payload = {"data": {"node": {"file": {"fileName": "mfa-screenshot.png", "downloadUrl": "/files/hidden/mfa-screenshot.png"}}}} if found else {"errors": [{"message": "not found"}]}
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if "id" not in req:
                self.send_response(202)
                self.end_headers()
                return
            if req["method"] == "initialize":
                result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}}, "serverInfo": {"name": "mock-probo", "version": "0"}}
            else:
                try:
                    out = call_tool(state, req["params"]["name"], req["params"]["arguments"])
                    result = {"content": [{"type": "text", "text": json.dumps(out)}], "isError": False}
                except KeyError as e:
                    result = {"content": [{"type": "text", "text": f"unknown tool or id {e}"}], "isError": True}
            body = json.dumps({"jsonrpc": "2.0", "id": req["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "session-1")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def main() -> int:
    fixture = HERE / "fixtures" / "type2"
    if not fixture.exists():
        sys.exit("Run python evals/make_fixture.py first.")
    server = serve(build_state(fixture / "export"))
    url = f"http://127.0.0.1:{server.server_address[1]}"
    soc2 = [sys.executable, str(HERE.parent / "soc2-audit" / "scripts" / "soc2.py")]
    with tempfile.TemporaryDirectory() as tmp:
        eng = Path(tmp) / "probo-engagement"
        eng.mkdir()
        cfg = load_yaml(fixture / "engagement.yaml")
        cfg["source"] = {"connector": "probo", "options": {"url": url, "organization_id": "org_1"}}
        dump_yaml(cfg, eng / "engagement.yaml")
        env = dict(os.environ, PROBO_TOKEN=TOKEN)
        ok = True
        for step in ("ingest", "check", "plan"):
            r = subprocess.run(soc2 + [step, str(eng)], env=env, capture_output=True, text=True)
            print(f"$ soc2.py {step}\n" + "\n".join((r.stdout + r.stderr).strip().splitlines()[:8]))
            if step != "plan" and r.returncode != 0:
                ok = False
                break
        if ok:
            manifest = json.loads((eng / "bundle" / "manifest.json").read_text())
            kinds = {}
            for art in manifest["artifacts"]:
                kinds[art["kind"]] = kinds.get(art["kind"], 0) + 1
            controls = read_csv(eng / "bundle" / "controls.csv")
            policy_arts = [a for a in manifest["artifacts"] if a["kind"] == "policy"]
            control_only = [a for a in policy_arts if a["title"] == "Policy: Control linked only"]
            policy_text = (eng / "bundle" / control_only[0]["path"]).read_text() if control_only else ""
            signer = read_csv(fixture / "export" / "populations" / "hires.csv")[0]["name"]
            signed = "SIGNED 2026-09-28" in policy_text and "APPROVED 2026-09-28" in policy_text and signer in policy_text
            hidden = list((eng / "bundle" / "evidence").glob("*mfa-screenshot.png"))
            hidden_ok = len(hidden) == 1 and hidden[0].read_bytes() == b"PNG-MFA-SCREENSHOT"
            ok = (len(controls) == 26 and kinds.get("evidence", 0) >= 135 and len(policy_arts) == 13
                  and kinds.get("population") == 3 and signed and hidden_ok)
            print(f"controls={len(controls)} artifacts={kinds} signed={signed} file={hidden_ok} -> {'OK' if ok else 'UNEXPECTED'}")
    server.shutdown()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
