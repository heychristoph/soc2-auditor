# Report, review packet and sign-off

## Build

```bash
python scripts/soc2.py validate <engagement> --final   # workpapers, QA, opinion, description
python scripts/soc2.py render <engagement>
python scripts/soc2.py packet <engagement>
```

`render` writes to `report/`:

- `soc2-type<N>-<org>-DRAFT.pdf` until sign-off, then `soc2-type<N>-<org>.pdf`: an AI Audit in the shape of a SOC 2 report. The cover, header and Section I say it is not an official SOC 2 audit. Section I is the model's report. Section II, management's assertion. Section III, management's system description. Section IV, the criteria, controls, tests and results. Section V, management's responses to exceptions.
- `workpapers.xlsx`: controls, samples, exceptions and the evidence register.
- `evidence-index.csv`: every artifact with its hash and the workpapers that cite it.
- `report-data.json`: the exact data the PDF was built from.

Report text comes from `assets/report/report-text.yaml` and the workpapers; the layout is `assets/report/report.typ`. A firm replaces the wording with its own quality-reviewed templates by editing the YAML, and its branding by editing the Typst file. Neither requires code changes.

## What the PDF may identify

The PDF names the service organization, the system, subservice organizations, vendors, `management.name` and title, and the model that signed. It names no one else. It contains no email address and no phone number. `validate --final` enforces this on every string the PDF can contain, and `signoff` and `render` both run that check.

- Section IV prints the workpaper `statement` when it is set, otherwise the control title from `controls.csv`. The source description stored in `control` is not printed.
- Section III prints `system.yaml` at the engagement root. It prints `bundle/system.yaml` only when that file is `management-approved`. A connector draft is omitted, and the section says the description was not provided.
- The same check covers procedures, exception descriptions, design rationales, scope limitations, sample notes, management responses, and the opinion basis. A name, inbox or phone number belongs in `observations`.
- `report/evidence-index.csv` and the Evidence sheet of `workpapers.xlsx` replace a title or path that contains an email address, a phone number, or another person's name with `[redacted]`. Files in `bundle/` are unchanged.

`review/packet.md` is the internal record. It quotes observations in full. Send the customer the PDF, not the packet and not the bundle.

## Sign-off

`review/packet.md` is the record of the opinion, every exception, design deficiency and scope limitation, low- and medium-confidence conclusions, and tester observations. Each entry links to the evidence files.

The model that ran the audit signs it:

```bash
python scripts/soc2.py signoff <engagement> --model "Grok 4.7"
python scripts/soc2.py render <engagement>
```

`signoff` re-validates everything and records the model name, today's date, and a digest of the workpapers, test plan, QA, opinion and bundle manifest. `render` writes the AI Audit PDF without the draft watermark. Section I is signed:

```
Grok 4.7
AI Auditor
September 30, 2026
Not an official SOC 2 audit.
```

Section II is signed with `management.name`, `management.title`, and that same date. Those two fields are the real person responsible for the system and their real role, taken from the evidence and written in `engagement.yaml` before sign-off. The report never prints a blank, a bracket, or a placeholder for a date, a name, or a title. Any later change to the work clears the signature and the next render is a draft again, still showing the recorded name, title, and date. Do not edit `signoff` by hand, and do not sign as a CPA or a firm.

## Management's part

- **System description.** Management owns it. The file readers see is `system.yaml` at the engagement root, written for the report and not copied from the connector draft. Put the approved version there with `status: management-approved`. The AI Audit can be signed before that; the report then says the description is not management-approved. With no root file, and with only a draft in the bundle, Section III says the description was not provided.
- **Assertion.** Section II is signed with the name and title in `engagement.yaml` `management`, and with the signature date. Set both from the evidence before sign-off.
- **Responses to exceptions.** Record them in each exception's `management_response`; they print in Section V.
