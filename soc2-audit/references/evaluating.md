# Evaluating exceptions and forming the opinion

Run `python scripts/soc2.py rollup <engagement>` to see each criterion with its controls and their conclusions (`review/rollup.md`). Then decide, criterion by criterion, whether the criterion was met, and write `opinion.json`.

## Is the criterion met?

An exception in one control does not by itself mean a criterion was not met. For each criterion with exceptions, weigh:

- **Rate and pattern.** One late item in a large sample may be isolated; repeated failures, or failures in a small population, point to a control that did not operate.
- **Cause.** A one-off human error is different from a missing process (a quarterly review that never happened).
- **Other controls.** Do other controls mapped to the same criterion, tested without exceptions, still achieve it? A compensating control only counts if it was itself tested.
- **Impact.** Could the failure have allowed the risk the criterion addresses (e.g. a terminated user keeping production access)?
- **Design gaps.** A criterion with no control, or only `design-deficiency` controls, is not met.
- **Scope limitations.** A criterion whose controls are all `not-tested` because evidence was withheld or unavailable cannot be evaluated.

## Opinion types

| Opinion | When |
|---|---|
| `unmodified` | Every criterion is met. Exceptions may still appear in Section IV. |
| `qualified` | One or more criteria are not met, or could not be evaluated, but the effect is confined to those criteria. |
| `adverse` | Failures are so pervasive that the controls as a whole did not meet the criteria. |
| `disclaimer` | Scope limitations are so significant that no opinion can be formed. |

When unsure between two opinions, choose the more conservative one and explain the judgment in the basis paragraph. The basis is printed in the AI Audit.

## opinion.json

```json
{
  "schema_version": 1,
  "opinion": "qualified",
  "criteria_not_met": [
    {"criterion": "CC6.2", "reason": "Terminated users kept access and a quarterly review was not performed.", "controls": ["C-12", "C-13"]}
  ],
  "scope_limitations": [],
  "basis": "The description states that ... One of five terminations tested ... As a result, controls were not operating effectively to meet CC6.2 throughout the period.",
  "prepared_by": "<agent / model>"
}
```

The `basis` paragraph is printed in the report under "Basis for Qualified Opinion" (or Adverse, or Disclaimer of). Write it in the firm's voice: what the description says, what testing found, and which criterion was affected. Leave it empty for an unmodified opinion. It names no one but `management.name`, and it contains no email address or phone number. A scope limitation in this file follows the same rule.

Every in-scope criterion must be covered by at least one tested control or appear in `criteria_not_met`; `validate --final` checks this.
