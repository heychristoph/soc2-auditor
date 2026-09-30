# Planning and sampling

`soc2.py plan` creates `testplan.csv` with one row per control, prefilled from the control matrix. Complete every row, then run `soc2.py sample`, which draws the samples and writes workpaper skeletons. Sampling is seeded from `engagement.yaml`, so the same plan always gives the same sample, and anyone can reproduce it.

## Columns

| Column | Values | How to decide |
|---|---|---|
| `frequency` | `annual`, `semiannual`, `quarterly`, `monthly`, `weekly`, `daily`, `multiple-daily`, `event`, `continuous` | How often the control operates, from its description and the policy. "Upon hire", "for each change", "when an incident occurs" are `event`. A configuration that is always on is `continuous`. |
| `nature` | `manual`, `automated`, `itdm` | `automated`: a system does it with no human step (MFA enforcement, encryption). `itdm`: a person acts on system output (reviewing a scan report). Otherwise `manual`. |
| `population` | `PO-...` artifact ID or empty | Required for `event` controls: the list of occurrences (e.g. `PO-terminations` for access removal). Look at the population files in `bundle/manifest.json`. |
| `sample_size` | number or empty | Leave empty to use the firm's table in `assets/sampling.yaml`. Override only with a reason in `notes`. |
| `notes` | text | Why you chose an unusual frequency, population or sample size. |

When the connector already filled a value, check it against the control description instead of trusting it.

## Type 2 (operating effectiveness over a period)

- Periodic controls: `sample` generates the occurrences in the period (months, quarters, ISO weeks, days) and samples from them. Items look like `2026-Q2`, `2026-03`, `2026-W14`, `2026-05-12`, or `2026` for annual controls.
- Event controls: items are rows of the population file whose date falls in the period.
- Automated and continuous controls: one item, `instance-1`. Testing one instance is enough only if general IT controls over change management and logical access are effective; note that dependency in the workpaper.
- A control with no occurrences in the period gets an empty sample. Its workpaper concludes `not-tested`, with a scope limitation explaining that the circumstances requiring the control did not occur.

## Type 1 (design and implementation as of a date)

Every control gets one item. Periodic controls get the item `latest`: find the most recent performance of the control on or before the as-of date and cite it. Event controls get one random item from their population. Automated controls get `instance-1`. Testing confirms the control is designed to meet its criteria and has been implemented; there is no operating effectiveness testing and no population completeness test.

## Changing the plan

If you change a row after sampling, run `sample` again. It refuses to overwrite a workpaper that already has results unless you pass `--force`, which discards those results. Never edit a workpaper's `plan` block directly; `validate` recomputes it and will reject the workpaper.
