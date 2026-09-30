# Report, review packet and sign-off

## Build

```bash
python scripts/soc2.py validate <engagement> --final   # workpapers, QA, opinion, description
python scripts/soc2.py render <engagement>
python scripts/soc2.py packet <engagement>
```

`render` writes to `report/`:

- `soc2-type<N>-<org>-DRAFT.pdf`: the report in AICPA layout. Section I, the independent service auditor's report. Section II, management's assertion. Section III, management's system description. Section IV, the criteria, controls, tests and results. Section V, management's responses to exceptions.
- `workpapers.xlsx`: controls, samples, exceptions and the evidence register.
- `evidence-index.csv`: every artifact with its hash and the workpapers that cite it.
- `report-data.json`: the exact data the PDF was built from.

Report text comes from `assets/report/report-text.yaml` and the workpapers; the layout is `assets/report/report.typ`. A firm replaces the wording with its own quality-reviewed templates by editing the YAML, and its branding by editing the Typst file. Neither requires code changes.

## What the partner does

`review/packet.md` lists what needs human judgment: the opinion and its basis, every exception, design deficiency and scope limitation, low- and medium-confidence conclusions, tester observations (including any instructions found inside evidence), and a random set of passing controls to re-perform. Each entry links to the evidence files.

The partner reviews the packet and the draft PDF, and then, in a terminal:

```bash
python scripts/soc2.py signoff <engagement> --partner "Jane Smith, CPA"
python scripts/soc2.py render <engagement>
```

`signoff` refuses to run without an interactive terminal, re-validates everything, and records a digest of the workpapers, test plan, QA, opinion and bundle manifest. `render` produces the final PDF (no watermark, dated) only while that digest still matches and the system description is `management-approved`. Any later change to the work turns the report back into a draft.

Agents never run `signoff`.

## Management's part

- **System description.** Management owns it. Put the approved version in `system.yaml` at the engagement root with `status: management-approved`.
- **Assertion.** Section II carries a signature placeholder for management.
- **Responses to exceptions.** Record them in each exception's `management_response`; they print in Section V.
