# Drata connector

Pulls a workspace through the Drata public API (v2).

## Configure

1. In Drata, create an API key with read access (Settings, API keys).
2. `export DRATA_API_KEY=...`
3. In `engagement.yaml`:

```yaml
source:
  connector: drata
  options:
    workspace_id: "<optional when the account has one workspace>"
    api_url: https://public-api.drata.com   # EU: https://public-api.eu.drata.com, APAC: https://public-api.apac.drata.com
```

## What is pulled

| Drata | Bundle |
|---|---|
| Controls and their SOC 2 requirements | `controls.csv` with Drata control codes as IDs |
| Evidence library, current versions | evidence artifacts, linked by control |
| Personnel (start and separation dates) | `PO-hires`, `PO-terminations` |
| Monitoring tests | one JSON export, current state only |

## Limits

- Drata does not hold the system description; management must provide `system.yaml`.
- Monitoring tests show the state at pull time, not a history across the period. Do not use them alone as Type 2 evidence.
- Not yet run against a live Drata account; check the ingest warnings on first use.
