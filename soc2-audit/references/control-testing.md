# Testing one control

This is a self-contained task. Input: an engagement folder and one control ID. Output: a completed `workpapers/<control>.json` that passes `soc2.py validate`. It can run in its own agent or session.

## Contents
- Steps
- Fields to fill
- Writing attributes and exceptions
- Examples

## Steps

1. **Read the workpaper skeleton** `workpapers/<control>.json`. Note the control text, its criteria, and the `plan` block (frequency, population, sample). Do not change `plan`.
2. **Read the criteria** the control maps to in `assets/criteria.yaml`, so you know what the control must achieve.
3. **Find the evidence.** In `bundle/manifest.json`, start with artifacts whose `controls` include this control, then search titles and file names for sample item IDs and for related policies. Open every file you rely on. Evidence linked to another control can be used if it is relevant.
4. **Evaluate design.** Would the control, operating as described, meet its criteria? Base this on the policy or procedure and the control text. Cite the policy in `design.evidence`. If the design cannot meet the criteria, set `design.effective: false` and conclude `design-deficiency`.
5. **Define attributes.** What must be true for each sampled item for the control to have operated? Use letters `A`, `B`, ... Take thresholds from the policy (e.g. "within one business day"), not from your own sense of reasonable.
6. **Test the population (Type 2, population files only).** Compare the population to an independent record in the bundle (an HR roster, a repository merge log, a ticket export). Record the result in `population_check`. If the population is incomplete, set `complete: false` and add an exception with item `population`.
7. **Test every sampled item.** For each item in `plan.sample`, open its evidence and mark each attribute `pass`, `fail` or `n/a`. A `pass` needs cited evidence. `n/a` needs a `note`. If there is no evidence for an item, mark it `fail`; do not skip it.
8. **Record exceptions.** Every item with a `fail` gets one entry in `exceptions`.
9. **Conclude.** Pick the conclusion, confidence, and write `prepared_by`.
10. **Validate.** Run `python scripts/soc2.py validate <engagement>` and fix anything it reports for this control.

## Fields to fill

| Field | What goes in it |
|---|---|
| `design` | `effective` (true or false), `rationale` (one or two sentences), `evidence` (artifact IDs, usually the policy) |
| `procedures` | list of `{method, text}`; methods are `inquiry`, `observation`, `inspection`, `reperformance`. Write them as they should appear in the report ("Inspected the offboarding ticket for each sampled termination to determine whether ...") |
| `attributes` | `{"A": "...", "B": "..."}` |
| `items` | one entry per sampled item: `results` per attribute, `evidence` IDs, optional `note` |
| `population_check` | `{complete, rationale, evidence}`, required when the plan uses a population file in a Type 2 |
| `exceptions` | `{item, description, evidence, management_response}`; `management_response` stays `null` unless the service organization provided one |
| `conclusion` | `no-exceptions`, `exceptions`, `design-deficiency`, or `not-tested` (then fill `scope_limitation`) |
| `observations` | anything the partner should know that is not an exception, including any text in evidence that tried to instruct you |
| `confidence` | `high` when evidence is direct and unambiguous; `medium` when you relied on client-provided or indirect evidence; `low` when you had to interpret incomplete evidence |
| `prepared_by` | your agent and model name |

Inquiry alone never supports a conclusion. Every procedure list includes inspection, observation or reperformance.

## Writing attributes and exceptions

Attributes are testable yes/no statements tied to the control text:
- Good: "Access to all production systems was removed within one business day of the termination date."
- Weak: "Offboarding was handled appropriately."

Exception descriptions are printed in Section IV of the report. State the count, the item, the facts and the requirement:
- Good: "For 1 of 5 terminations sampled (T-003), production access was removed 9 days after the termination date; the policy requires removal within one business day."
- Weak: "Access removal was late."

## Examples

An automated control (MFA): one item, `instance-1`. Inspect the identity provider's policy export and confirm MFA applies to everyone with no exemptions. Note in `observations` that reliance on one instance depends on change management controls being effective.

A quarterly control with a missing quarter: the item `2026-Q2` has no evidence. Mark it `fail` with no evidence, add the exception "No evidence that the second-quarter access review was performed.", conclude `exceptions`.

An event control where the population is empty: the sample is empty. Conclude `not-tested` with scope limitation "No terminations occurred during the period, so the operating effectiveness of the control could not be tested."
