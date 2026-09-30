# Vanta connector

Pulls one audit through the Vanta Auditor API. Available to audit firms registered as Vanta audit partners; the firm sees only audits assigned to it.

## Configure

1. In Vanta, open the Auditor API section and create an application. Note the client ID and secret.
2. `export VANTA_CLIENT_ID=... VANTA_CLIENT_SECRET=...`
3. In `engagement.yaml`:

```yaml
source:
  connector: vanta
  options:
    audit_id: "<optional when the firm has one active audit>"
    api_url: https://api.vanta.com     # https://api.vanta-gov.com for Vanta Gov
```

The token is requested with the scopes `auditor-api.audit:read auditor-api.auditor:read`.

## What is pulled

| Vanta | Bundle |
|---|---|
| Audit controls | `controls.csv`; criteria parsed from the control's framework sections |
| Audit evidence and its download URLs | evidence artifacts, linked by related control name |
| In-scope people (start and end dates) | `PO-hires`, `PO-terminations` |
| Code changes | `PO-changes` |

## Limits

- Vanta does not hold the system description; management must provide `system.yaml`.
- Automated test results reflect Vanta's snapshot at the time they were shared with the audit, not a history across the period. For Type 2, confirm snapshots were taken during the period, or treat the control as tested at one point in time.
- Not yet run against a live Vanta tenant; check the ingest warnings on first use.
