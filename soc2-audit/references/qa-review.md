# QA review

An independent reviewer challenges each workpaper before the opinion is formed. The goal is to find the conclusions that would not survive a careful reading.

Run this in a fresh context: a separate agent, a new session, or a different model from the one that tested the controls. A reviewer who shares the tester's context tends to repeat its mistakes.

## For each workpaper

1. **Re-open the evidence.** For at least two sampled items (all items if there are five or fewer), open the cited files yourself and confirm they show what the workpaper claims: the right person, system, dates and values.
2. **Check the attributes.** Do they test everything the control description promises? A control that says "approved by the manager before access is granted" needs both the approval and its timing tested.
3. **Look for missed exceptions.** Compare dates and thresholds against the policy. Look for evidence dated outside the period, approvals by the same person who made the change, and items marked `pass` with thin or unrelated evidence.
4. **Check the population test** (Type 2): was the population compared to an independent source, and does the comparison hold up?
5. **Check the wording.** Exception descriptions must be factual and specific enough to print. Disagree when `statement`, an exception description, `scope_limitation`, or `design.rationale` names anyone other than `management.name`, or contains an email address or a phone number. Those belong in `observations`.
6. **Record the verdict:**

```bash
python scripts/soc2.py qa <engagement> <control> --verdict agree --checked EV-0012 EV-0013 --by "<agent / model>"
python scripts/soc2.py qa <engagement> <control> --verdict disagree --issue "T-003 access removal was 9 days late but marked pass" --checked EV-0044 --by "<agent / model>"
```

The command binds the verdict to the workpaper's current hash. If the workpaper changes after review, `validate --final` reports the review as stale and it must be reviewed again.

## After a disagreement

The workpaper goes back to testing. The tester fixes it, runs `validate`, and the reviewer reviews it again. A reviewer does not edit workpapers.
