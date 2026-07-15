---
title: Real-trial evidence workspace
status: awaiting_human_domain_release_and_participants
evidence_type: templates_only
---

# Real-trial evidence workspace

This directory contains templates only. It does not contain release evidence,
participant records, or trial outcomes. Do not treat the presence of these
files as evidence that a trial has started or concluded.

## Current gate

Real collection may begin only after all of the following are supplied by
people with the appropriate authority:

- A human domain-release reference that identifies the reviewer, review scope,
  date, decision, and remaining risks.
- Consent or authorization references for each real participant.
- Actual participant, recorder, observation, revision, and retest data.

Do not infer any of those facts from this repository, generate them, or use a
placeholder as a release reference.

## Using these templates

1. Use [trial-protocol.md](trial-protocol.md) unchanged for every participant.
2. Copy [trial-record-template.md](trial-record-template.md) only when a real
   participant and recorder are present.
3. Create a session summary only from observed data that validates against
   [session-summary.schema.json](session-summary.schema.json).
4. Keep missing facts explicit. A blank field, pending result, or absent record
   is not permission to supply a value.

## Boundary

Engineering verification and browser checks are separate from real-trial
evidence. This workspace remains in the stated awaiting status until genuine
human release and participant records are available.
