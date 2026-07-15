---
title: Real participant trial protocol
status: awaiting_human_domain_release_and_participants
---

# Real participant trial protocol

## Preconditions

Before starting a session, the recorder must have:

- A real `release_approval_ref` tied to a human domain-release decision.
- A real participant role and consent or authorization reference.
- A recorder identity and a way to capture start/end times, observations, and
  any follow-up retest.

If a precondition is missing, do not start or synthesize a session record.

## Required sequence for every participant

Run the following sequence in the listed order. Use one representative task
per data domain and record actual completion status, errors, and feedback for
every item.

1. Text task — open one published text lesson, perform the stated learner
   action, and record the observed feedback.
2. Image task — open one published image lesson, perform the stated learner
   action, and record the observed feedback.
3. Audio task — open one published audio lesson, perform the stated learner
   action, and record the observed feedback.
4. Video task — open one published video lesson, perform the stated learner
   action, and record the observed feedback.
5. Scenario comparison — compare two supported scenarios for the same data
   domain and record what changed in the rule context or displayed plan.
6. Enterprise-task conversion — enter a representative business request and
   record either generated cards or the requested clarification.
7. Structured diagnosis — upload a real, authorized structured export and
   record the reported status, issues, and whether mastery changed.
8. PRE remediation plan — select the relevant capability or diagnostic result
   and record the displayed prerequisite-ordered remediation plan.

## Session conduct

- Record observed facts, including failures and incomplete steps, without
  converting them into a positive conclusion.
- Keep participant identifiers out of public artifacts unless the consent or
  authorization reference permits disclosure. Use an approved participant
  reference where appropriate.
- Record revision decisions with their rationale. Do not state that a revision
  resolved an issue until an actual retest result exists.
- End the session by recording the finish time, participant feedback, and any
  required retest. Do not create a release decision from session data.

## Required outputs

For every real participant, retain one completed record based on
[trial-record-template.md](trial-record-template.md) and one session summary
that validates against [session-summary.schema.json](session-summary.schema.json).
