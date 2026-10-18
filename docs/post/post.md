# NetCortex: an on-call network engineer that runs on a Mac mini

*It notices when the network goes bad, works out why, tests a fix on a virtual router, and asks a person before it changes anything.*

## The 9 pm problem

In Pakistan, home internet gets slow in the evening. Families stream. Kids play online games. Everyone shares the same uplink. For a small ISP or a gaming café, that is also when the phone starts ringing.

These operators run on one or two technicians and a few MikroTik routers. They have no network operations centre. They can't afford one.

NetCortex is built for them. It watches a site, opens an incident when something goes wrong, explains the likely cause in plain English, and drafts a short message for customers in English and Urdu. It proposes one fix and tests it on a virtual MikroTik router first. A person approves it. If the fix doesn't help, NetCortex undoes it.

We think a small ISP or a gaming café would pay a small monthly fee per site for that. We have not sold it to anyone yet.

## Demo

[VIDEO PLACEHOLDER]

[SCREENSHOT: dashboard, an incident awaiting approval, with the router commands and the dry-run result]

[SCREENSHOT: Sentry trace of one incident, showing the `gen_ai.chat` spans and their token counts]

[SCREENSHOT: the timeline of the incident that rolled itself back]

Everything in the video runs at home: a laptop, a Mac mini, and a virtual router. The incidents are simulated. The agent, the workflows, the router commands and the traces are real. The "Honest limits" section says exactly where the line is.

## How it works

```
home collector (pings, DNS lookups) ──┐
simulated site (scripted incidents) ──┴──> TimescaleDB (Tiger Cloud)
                                                │  every 60 s
                                                v
                                   rule-based detector, per site
                                                │  anomaly
                                                v
                                Temporal incident workflow
                                                │
                Gemma 4 agent with tools ──> report + one fix template + params
                                                │
                       validate params ──> dry run on MikroTik CHR
                                                │
                              a person approves in the dashboard
                                                │
                          apply on CHR ──> watch ──> verify
                                                │
                 improved: resolved      not improved: automatic rollback
```

1. **Collect.** A small Python collector pings its targets and times DNS lookups every 10 seconds. Rows go into TimescaleDB hypertables on Tiger Cloud.
2. **Detect.** One Temporal workflow per site wakes every minute. It loads the last 30 minutes and runs a rule-based detector. If something is wrong and no incident is open for that site and cause, it opens one.
3. **Investigate.** A second workflow runs the agent: Pydantic AI on Gemma 4 E4B. The agent has tools to read metrics and forecasts and to list the fix templates allowed for a cause. It returns a typed report: a summary, the likely cause, its confidence, evidence, one template, the template's parameters, and the customer messages.
4. **Check.** Code renders the router commands from the template and tests them on CHR, MikroTik's virtual router.
5. **Decide.** The dashboard shows the report, the exact commands, the rollback and the dry-run result. Approve or Reject sends a Temporal signal. The workflow waits up to two hours.
6. **Apply and verify.** After approval, the fix goes onto CHR. The workflow watches the key metric for five minutes, then compares it with before the incident. Better: resolved. Not better: it rolls the fix back.

Each model request and each tool call is its own Temporal activity, through Pydantic AI's `TemporalAgent`. If the worker crashes halfway through an investigation, it resumes where it stopped. Waiting two hours for a person costs nothing.

## Safety: the model never writes a router command

Letting a language model type commands into a router is a bad idea. So it doesn't.

- **Templates only.** There are four fix templates in YAML: `queue_limit`, `failover_route`, `priority_queue` and `dns_servers`. Each has typed parameters, apply commands, rollback commands, and a rule for what "better" means. Gemma picks a template and fills in the parameters. Code renders the commands. A fifth choice, `none`, means "tell the owner, change nothing".
- **Parameters are checked.** Types, ranges and IP formats are validated. The bandwidth cap has one more rule: it must be at most half of the subscriber's current rate. If a check fails, the error goes back to Gemma for one retry. If it fails again, the incident gets a notify-only report.
- **Every fix is tested first.** The checker exports the CHR config, applies the fix, exports again and diffs, rolls back, and exports a third time. A fix passes only if it changed something and the config came back exactly as it was. All four templates pass on the laptop. GitHub Actions boots its own CHR and runs the same test on pull requests that change the fix code.
- **Names that can't collide.** Everything a fix creates is named after its incident, like `nc-1a2b3c4d`. Rollback removes only those names.
- **Old config is never touched.** We found a bug here while testing. If a fix's `add` command failed because a queue with that name already existed, the checker still ran the rollback, and the rollback deleted the older queue. Now a failed fix undoes only what it created. If nothing went in, it rolls back nothing. If objects with its name already exist, it refuses to start.
- **A person approves every change.** And the code only applies to the virtual router. Real routers are not wired up.
- **Automatic rollback.** This one happened for real.

### The rollback that happened

During testing we injected an uplink outage. About ninety seconds in, our rule-based detector saw DNS lookups failing and called it "slow DNS". Gemma agreed, with confidence 0.75, and proposed switching the router's resolvers to 1.1.1.1 and 8.8.8.8. The dry run passed: the commands were valid. We approved it.

Five minutes later the workflow measured DNS lookups again. Before: 12.0 ms. After: 12.3 ms. The template asks for a 30% drop. The workflow rolled the change back on its own and closed the incident as "rolled back". The whole incident took 334 seconds.

The fix was wrong because our detector was wrong. The safety net caught it. We then fixed the detector: an outage now takes priority over slow DNS, and slow DNS needs healthy pings. A test reproduces the old mistake.

## Why open models

Gemma 4 E4B runs in Ollama on a Mac mini M4 with 16 GB of memory. The laptop reaches it over the home Wi-Fi.

- **Privacy.** The agent sees subscriber IP addresses, traffic rates and router config. None of it leaves the building.
- **It works when the internet doesn't.** The tool that diagnoses a dead uplink can't depend on that uplink.
- **Cost.** No per-token bill. A small ISP buys a small computer once.

### Thinking on or off?

Gemma 4 can "think" before it answers. We tried both on three hand-made incidents (a heavy user, an uplink outage, slow DNS), two runs each:

| | Thinking off | Thinking on |
|---|---:|---:|
| Median time per investigation | 9.0 s | 33.6 s |
| Right cause | 6/6 | 4/6 |
| Right fix template | 5/6 | 3/6 |
| Right parameters | 5/6 | 3/6 |
| Tool calls per run (average) | 4.3 | 4.8 |

On these cases, thinking was almost four times slower and less accurate. It is a small sample, but the choice was easy. NetCortex runs with thinking off and temperature 0.2.

### How often does it get it right?

We rebuilt the inputs of our end-to-end runs and called the agent 11 times: five heavy users, three outages, three slow-DNS cases. Ten of the 11 produced a valid report with the right template and the right parameters. Two of those needed one retry after a validation error. The eleventh failed twice and fell back to a notify-only report: Gemma kept filling in a field that only the news tool is meant to fill. It failed safe, which is the point.

## Data

### A live home connection

The collector has run on a home connection in Pakistan since the evening of 18 October. Every 10 seconds it sends five pings to each of five targets and times DNS lookups through two resolvers. By early on 19 October it had about 12,500 rows, around 1,800 per target.

| Target | Median | 95th percentile | Average loss |
|---|---:|---:|---:|
| Home router | 3.3 ms | 15.6 ms | 0.03% |
| First upstream hop | 8.0 ms | 15.6 ms | 0.07% |
| 1.1.1.1 (ping) | 6.8 ms | 28.3 ms | 0.11% |
| 8.8.8.8 (ping) | 21.9 ms | 33.4 ms | 0.02% |
| Valve CS2 relay, Dubai (ping) | 39.1 ms | 72.6 ms | 0.11% |
| DNS lookup via 1.1.1.1 | 11.2 ms | 38.2 ms | 0.19% |
| DNS lookup via 8.8.8.8 | 34.1 ms | 67.1 ms | 0.31% |

One finding stood out. On this connection, DNS lookups through 8.8.8.8 take three times as long as through 1.1.1.1: 34.1 ms against 11.2 ms at the median. The ping gap is similar (21.9 ms against 6.8 ms), so it looks like the network path, not the resolver. A router using 8.8.8.8 here pays about 20 ms on every lookup. That is exactly the kind of change the `dns_servers` template exists for.

### Simulated incidents

The incidents in the demo happen on a simulated site, `sim-tower`. It is laid out like the virtual router: two uplinks, three subscribers, and an ISP resolver. An injector writes 30 minutes of normal data, then the incident, then a recovery.

The partner built a fuller simulator, calibrated with 11,819 public RIPE Atlas ping measurements from three probes on Pakistani networks over seven days. It covers three more sites and seven causes. It is in the repository with its tests, but the live demo doesn't use it yet.

## Observability with Sentry

Every incident is one Sentry trace, and the trace ID is the incident ID. Each Temporal activity is a transaction inside it: the model requests, the tool calls, the dry run with its CHR API calls, the apply, the verify, every status change.

Two things we learned on the way:

1. **Sentry's Pydantic AI integration recorded nothing.** Under `TemporalAgent`, the agent loop runs inside Temporal's workflow sandbox, and the model calls run in activities. The integration hooks the loop, so it never saw a model call. We wrapped the model instead. Now each Gemma request opens a `gen_ai.chat` span inside its activity, with the model name and token counts. In one heavy-user incident, Gemma made five calls: 1,136 to 1,879 input tokens, 16 to 238 output tokens, 0.6 to 14.5 seconds each.
2. **A monitoring span showed up inside incident traces.** Activities run side by side and shared one Sentry scope. Now each activity gets its own. A test runs two activities interleaved to prove it.

Traces (they need a Sentry login, so screenshots are above):

- Heavy user, with `gen_ai` spans: https://aun-t9.sentry.io/explore/traces/trace/1ffec8847bc44c8f89a8b0b66a04e4f3
- The rollback: https://aun-t9.sentry.io/explore/traces/trace/5837ffbbe394489280260f42a5c969e4

## Results

End-to-end runs on the full stack: the laptop, Gemma on the Mac mini, CHR and Tiger Cloud. A test script pressed Approve a few seconds after each request. Times after the first column are from the moment the incident opened.

| Scenario | Fault to incident | Report | Dry run passed | Applied | Outcome | Key metric, before to after |
|---|---:|---:|---:|---:|---|---|
| Heavy user | 66 s | 14.6 s | 20.8 s | 29.0 s | resolved at 332 s | ping to 1.1.1.1: 56.0 to 24.9 ms |
| Uplink down | 151 s* | 14.2 s | 20.9 s | 28.4 s | resolved at 331 s | loss to 1.1.1.1: 83.3% to 0% |
| Slow DNS | 121 s | 11.8 s | 17.9 s | 24.8 s | resolved at 328 s | DNS via ISP resolver: 440.5 to 23.3 ms |
| Outage read as slow DNS | about 90 s | 18 s | 24 s | 31 s | rolled back at 334 s | DNS via 1.1.1.1: 12.0 to 12.3 ms |
| Heavy user, 60 s watch | 77 s | 17.3 s | 24.2 s | 30.2 s | resolved at 93 s | ping to 1.1.1.1: 52.1 to 32.1 ms |

\* This incident waited out a cooldown. After an incident closes, a new one for the same site and cause can open only four minutes later.

The "after" numbers improve because the injector scripts the recovery (see below). What the table shows is that each step ran, on real systems, in the time shown.

## Honest limits

- **The incidents are simulated.** CHR carries no customer traffic, so a fix there can't change the measurements. The recovery after a fix is scripted. What is real: the detection on the data in the database, Gemma's reasoning and tool calls, the router commands, the dry run and apply on a real RouterOS, the workflow, the verification logic, the rollback and the traces.
- **The detector that opens incidents is rule-based.** TabPFN is wired in as an optional second opinion but has never answered a real incident. In the partner's one cloud test, it ran end to end but guessed the wrong cause, took 272 seconds to set up and 115 seconds per detection. Our monitor runs every 60 seconds.
- **Two tools return nothing yet.** Runbook search (EmbeddingGemma and pgvector) is built, but the index is empty. The outage-news check has no SerpApi key and reports "unavailable". The agent handles both cases, but they add nothing today.
- **Narrow scope.** MikroTik RouterOS only, four fix templates, and never a real router.
- **Small evaluation.** Eleven agent runs, six per thinking mode, and a handful of end-to-end runs.

## What's next

- Run on a real router in read-only mode at one real site, then allow approved fixes.
- Index the MikroTik documentation, so the agent can cite it.
- Add more causes and templates: uplink congestion and broken game routes first.
- Try TabPFN again as a second opinion once a detection fits in the monitor's minute. Its cloud API sends metrics to Prior Labs, and its free licence is non-commercial, so a paid product would need a commercial licence.

## Built with

- **Gemma 4 E4B**: the agent, running locally in Ollama on a Mac mini.
- **Temporal**: durable monitoring and incident workflows, human approval as a signal.
- **Sentry**: one trace per incident, with `gen_ai` spans and token counts.
- **Tiger Data**: TimescaleDB on Tiger Cloud for every metric and event.
- **GitHub Actions**: lint and tests on every push to main and every pull request, plus a CHR boot that tests every fix template.
- **Entire**: session checkpoints on 42 of our commits.

Also: Pydantic AI, FastAPI, MikroTik CHR in QEMU, icmplib, dnspython and uv.

Built by Aun Raza and Muhammad Anas Muqeem. Code: https://github.com/aunraza19/NetCortex
