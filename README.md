# soc2-auditor

Example AI Audit report: [DoneThat SOC 2 Type 1](https://trust.donethat.ai/en/documents/qE94tnY9AAEAGQAAAaD7eRKWtWoj5-GG).

An agent skill that runs an AI Audit modeled on a SOC 2 Type 1 or Type 2 examination: it pulls evidence from the client's compliance platform, tests every control against the Trust Services Criteria, and produces a PDF signed by the model that ran it. The report says it is an AI Audit, not an official SOC 2 audit.

It follows the open [Agent Skills](https://agentskills.io/specification) format, so the same `soc2-audit/` folder works with Claude Code, Codex, Gemini CLI, Cursor, GitHub Copilot and other agents that read `SKILL.md`. All deterministic work runs in plain Python scripts, so nothing depends on one vendor's agent features.

## How an engagement runs

```
init ──> ingest ──> check ──> plan ──> sample ──> test ──> validate ──> QA ──> opinion ──> signoff (model) ──> render + packet
          │                                        │                    │
     connector writes                       agent writes one      fresh context or
     bundle/ (hashed)                       workpaper per control  another model reviews
```

- **Connectors** (`folder`, `probo`, `vanta`, `drata`) turn a source into an evidence bundle. Every file is hashed at ingest.
- **The agent** judges: evaluates design, tests each sampled item, writes exceptions, and forms the opinion.
- **Scripts** count: seeded sampling, validation, criterion rollup, and rendering the report from workpapers.
- **The model** signs `signoff --model` with its own name. Until then every PDF is watermarked DRAFT. The signed PDF is an AI Audit, not an official SOC 2 audit. Any later change to the work clears the signature.

## Install

```bash
git clone git@github.com:heychristoph/soc2-auditor.git
pip install -r soc2-auditor/soc2-audit/scripts/requirements.txt
```

Then make `soc2-audit/` visible to your agent: copy or symlink it into the agent's skills directory (for Claude Code, `~/.claude/skills/soc2-audit`), or tell the agent to read `soc2-audit/SKILL.md`.

## Quick start

```bash
python soc2-audit/scripts/soc2.py init ./acme-2026 --type 2 --start 2026-01-01 --end 2026-06-30 \
  --org "Acme, Inc." --system "Acme Platform" \
  --categories security,availability,confidentiality --connector probo --option organization_id=<id>
export PROBO_TOKEN=...
```

Then ask your agent: *"Run the AI Audit in ./acme-2026."* The agent signs the report with the model that ran it. `soc2.py status ./acme-2026` shows progress and the next step at any time.

## Design guidelines

1. **One contract: the engagement folder.** All state is files described by JSON Schemas in `soc2-audit/assets/schemas/`. Any step can be rerun or resumed by any agent.
2. **Vendor names stay in the connectors.** A new source is one Python module with a `pull()` function plus one reference page. Nothing downstream changes.
3. **Scripts count, agents judge.** Hashing, sampling, validation and report text are code. Evidence inspection, design evaluation and the opinion are the agent's.
4. **No conclusion without evidence.** Every pass cites hashed artifacts; the validator rejects anything uncited, and the plan block is recomputed so samples can't be changed.
5. **The report is rendered, never written.** Report text comes from `assets/report/report-text.yaml` plus the workpapers, so the PDF cannot disagree with the work. Firms replace the wording and the Typst layout without touching code.
6. **Evals before claims.** Synthetic engagements with planted defects measure what any agent and model actually catches.

## Repository layout

```
soc2-audit/                  the skill (self-contained, spec-valid)
├── SKILL.md                 workflow and rules
├── references/              one page per step and per connector
├── scripts/                 soc2.py CLI, connectors/
└── assets/                  criteria, sampling table, schemas, report template and wording
evals/                       fixtures, oracle, graders, agent runner, Probo mock
```

## Evals

```bash
python evals/make_fixture.py                    # synthetic Type 1 and Type 2 engagements
python evals/run.py --case type2 --agent oracle # model-free regression test of the scripts
python evals/run.py --case type2 --agent 'claude -p --permission-mode bypassPermissions {prompt}'
python evals/test_probo_connector.py            # Probo connector against a local mock
```

See [evals/README.md](evals/README.md).

## Status

- Tested: the full pipeline with the oracle on both fixtures (score 1.0), the folder connector, and the Probo connector against a mock built from Probo's published MCP specification.
- Not yet tested: Probo, Vanta and Drata against live accounts; a full run by a real agent on the fixtures.
- Not included yet: SOC 3, bridge letters, the inclusive method for subservice organizations, and Processing Integrity and Privacy fixtures (the criteria are included).

## Professional responsibility

This tool produces an AI Audit. It is not an official SOC 2 audit, not an AICPA attestation, and not a report a CPA firm can issue. The model that ran the work signs the PDF, and the report says so. The Trust Services Criteria in `assets/criteria.yaml` are paraphrased.
