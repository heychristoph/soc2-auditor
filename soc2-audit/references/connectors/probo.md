# Probo connector

Pulls from [Probo](https://github.com/getprobo/probo), hosted (`us.probo.com`, `eu.probo.com`) or self-hosted. The script calls Probo's MCP API over HTTP, so the agent does not need MCP support.

## Configure

1. In Probo, give the audit firm a user in the client's organization, and create an OAuth access token with read scopes (at least `v1:org`, `v1:control`, `v1:document`, `v1:risk`, `v1:third-party`, `v1:iam`, `v1:access-review`, `v1:audit`).
2. Set the token in the environment: `export PROBO_TOKEN=...`
3. In `engagement.yaml`:

```yaml
source:
  connector: probo
  options:
    url: https://us.probo.com          # or the self-hosted root
    organization_id: "<Probo organization GID>"
    framework_id: "<optional; defaults to the framework named SOC 2>"
```

## What is pulled

| Probo | Bundle |
|---|---|
| Framework controls (e.g. `CC6.1`) | criteria; each measure inherits the criteria of the framework controls it is linked to |
| Measures | `controls.csv` rows with IDs `M-001`, `M-002`, ... (`source_ref` keeps the Probo ID) |
| Measure evidence (files and links) | evidence artifacts, `obtained: direct` for files, `client` for links |
| Documents linked to framework controls | latest published version as a policy artifact |
| People (contract start and end) | `PO-hires` and `PO-terminations` for the period |
| Third parties | `PO-vendors` |
| Risks, access review campaigns | JSON exports as evidence |
| Organization context | draft `system.yaml` (status `draft`) |

## Limits

- Measures have no frequency or nature in Probo; fill them in `testplan.csv`.
- Populations are linked to controls by keywords (termination, onboarding); confirm them in `testplan.csv`.
- Measures marked not applicable are excluded, and requested but unfulfilled evidence is skipped; both are listed as ingest warnings, which `check` repeats.
- The system description needs management's review before the report can be final.
- Tested against a local mock of Probo's published MCP API (`evals/test_probo_connector.py`), not yet against a live instance; check the ingest warnings on first use.
