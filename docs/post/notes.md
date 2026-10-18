# Post research notes

Keep only findings backed by a source, a reproducible run, or a clearly labeled team observation. Record the date, method, and limits with each result. Do not invent performance numbers, customer feedback, first users, or claims that the hosted demo is live.

## Evidence log

- 2026-10-18: Build plan identifies small WISPs, gaming cafes, and freelance network engineers as intended users. This is a target audience, not evidence of a customer interview or first user.
- 2026-10-18: The planned hosted demo uses replayed/simulated data. Any published demo must label that data clearly.
- Pending: measured detector evaluation, model/runtime details, real baseline provenance, first-user feedback, and hosted demo URL/status.

## Draft post outline

NetCortex is being built for small network operators who need an affordable way to spot deteriorating links and review a tested RouterOS fix. The intended flow collects or replays network metrics, detects unusual behavior, explains the evidence, tests a constrained fix on a virtual router, and waits for a human decision.

Open-weight local inference is intended to keep network context on-site, support diagnosis during internet outages, and avoid per-token charges for the core workflow. These are design goals; claims about measured privacy, reliability, cost, or accuracy require implementation and evidence.

The hosted demo is planned to use simulated/replayed telemetry. TabPFN cloud sends anonymized metrics to its provider and its current license terms may restrict commercial use; verify the applicable terms before making product claims. Cloud voice and outage-search integrations are optional and may require paid credentials.

Before publication, replace this draft with verified implementation details, evaluation results, limitations, a working demo link if available, and an actual first-user account only if one exists and consents to being described.
