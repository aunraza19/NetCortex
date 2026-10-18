# NetCortex: a second set of eyes for a small network operator

Draft for the team submission. This is not published. Aun supplies the
architecture, agent and router-safety sections. Replace every pending integration
with verified evidence before describing it as working.

## Who might pay for this?

A neighbourhood ISP or gaming cafe can have a busy evening and no dedicated
network operations team. A slow game server, a full uplink and one demanding
subscriber can all reach the owner as the same complaint: "the internet is slow."
The useful product is a shorter path from that complaint to evidence and an
appropriate action.

Our intended customers are small wireless ISPs, cafe owners and freelance network
engineers who already operate MikroTik equipment. We have not yet established
willingness to pay. The first-user section must report an actual conversation or
walkthrough rather than treating this target audience as customer validation.

## What the partner work builds

Workstream B supplies reproducible telemetry scenarios, a detector adapter,
source-linked RouterOS documentation retrieval, voice/outage-check adapters and
the operator dashboard. The shared API, agent, durable workflows and virtual-router
test harness belong to Aun's workstream.

The intended walkthrough starts with a site and a selected incident. The owner
sees the observations, the explanation, the proposed commands, the rollback
commands and the router-test result before deciding. The dashboard treats a
decision as a request to the workflow; it does not equate clicking Approve with a
successful router change.

The current integration status and validation evidence must accompany any demo.
Fixture tests alone do not establish that the live API, model or virtual router
works. Hosted fixture mode is labelled **Demo: replayed data**.

## The data story

We wrote a generator rather than hand-writing plausible-looking metric rows.
Its inputs describe three sites, their uplink capacities, backhaul interfaces,
targets and subscriber counts. Seeded demand and queueing effects produce
repeatable normal periods and incidents.

The real-baseline ingestion path discovers public Pakistani RIPE Atlas probes and
ping measurements. It derives latency, jitter and packet loss from the packet
results, retains measurement/probe provenance and caches bounded downloads.
The measured run downloaded 11,819 observations from three Pakistani probes
across three ASNs, spanning October 11?17, 2026. One measurement returned all
seven days; another returned four days and recorded three timeout gaps. The
[provenance summary](../../data/ripe-baseline-summary.json) and
[calibration report](../../data/calibration-report.md) preserve that coverage.
Root-server ping statistics can be explicitly opted into as a public-DNS
reachability proxy, with the route-transfer uncertainty recorded. Other target
roles retain clearly identified defaults.

We also found a useful boundary in the original design: aggregate interface
counters cannot identify an individual heavy user, and a ping to a DNS resolver
does not measure a DNS lookup. Experimental subscriber and DNS fixtures stay
separate until the shared telemetry contract can carry those observations.

## Why open models matter to the product

The on-site design uses local Gemma inference and local EmbeddingGemma retrieval
so network context can remain on the operator's own machine. Local execution is
also valuable when the connection being diagnosed is unavailable. These are
deployment goals that must be demonstrated with a real offline run before we
claim the whole product works without internet access.

The code can expose the model boundaries and measured failures for inspection.
That makes it possible to evaluate a different model or narrow its task without
rewriting the dashboard and workflows.

Cloud add-ons have different boundaries. TabPFN cloud receives the submitted
feature data; ElevenLabs receives alert text; SerpApi receives the outage query.
They must be optional and described accurately. Our code's MIT license does not
replace the licenses of model weights, datasets or third-party services. Check
the applicable [TabPFN model terms](https://github.com/PriorLabs/TabPFN) before
commercial use.

## What we measure

Training, threshold selection and the final evaluation use separate cases.
The report distinguishes event detection from cause classification and records
false alerts, detection delay, parameter validity, router-test outcomes and
latency only where those checks actually ran.

Results are linked from the repository's validation and evaluation reports.
Provider-free unit tests establish our parsing, failure handling and UI behavior;
they do not count as model-accuracy or live-integration results.

## First-user notes to collect

- Operator's role and existing MikroTik workflow, with permission to describe it.
- What they expected to see before approving a change.
- Which evidence they trusted or found confusing.
- Whether the tool would save time, and whether they would pay for it.
- What they requested next.

No user, quote, payment or endorsement has been collected for this draft.

## Submission checklist

- Link the working demo only after an unaffiliated visitor can complete it.
- Include measured results and their fixture/cloud/local labels.
- Include actual model/checkpoint identities and data provenance.
- Link selected verified coding-session provenance if available.
- Add Aun's architecture, agent, approval and rollback evidence.
- Use the [official submission template](https://dev.to/challenges/hacktoberfest-week2-2026-10-12)
  and required tags; publish before the verified deadline.
