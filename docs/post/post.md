# NetCortex: an on-call network engineer that runs on a Mac mini

*It notices when the network goes bad, works out why, tests a fix on a virtual router, and asks a person before it changes anything.*

## The 9 pm problem

In the evening, everyone is online at once. Families stream, kids play online games, and the whole street shares one uplink. For a small ISP or a gaming café in Pakistan, that is when the phone rings.

These operators run on one or two technicians and a few MikroTik routers. They have no network operations centre, and they can't afford one.

NetCortex is built for them. It opens an incident when something goes wrong, explains the likely cause in plain English, and drafts a customer message in English and Urdu. It proposes one fix, tests it on a virtual MikroTik router, and waits for a person to approve it. If the fix doesn't help, it undoes it.

We think a small ISP or gaming café would pay a small monthly fee per site for that. We haven't sold it to anyone yet.

## Demo

[VIDEO PLACEHOLDER]

[SCREENSHOT: dashboard, an incident awaiting approval, with the router commands and the dry-run result]

[SCREENSHOT: Sentry trace of one incident, with the `gen_ai.chat` spans and their token counts]

[SCREENSHOT: the timeline of the incident that rolled itself back]

Everything runs at home: a laptop, a Mac mini and a virtual router. The incidents are simulated; the agent, workflows, router commands and traces are real. "Honest limits" draws the line.

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

A Temporal workflow per site wakes every minute and runs a rule-based detector over the last 30 minutes. When it finds a problem, an incident workflow runs the agent: Pydantic AI on Gemma 4 E4B, with three tools to read metrics, read forecasts and list the fix templates allowed for a cause. The agent returns a typed report: summary, likely cause, confidence, evidence, one template with its parameters, and the customer messages.

Code renders the router commands from the template and tests them on CHR, MikroTik's virtual router. The dashboard shows the report, commands, rollback and dry-run result. Approve sends a Temporal signal; the workflow waits up to two hours. Then the fix goes onto CHR and the workflow compares the key metric with before the incident. Better: resolved. Not better: rolled back.

Each model request and tool call is its own Temporal activity, through Pydantic AI's `TemporalAgent`. If the worker crashes mid-investigation, it resumes where it stopped.

## Safety: the model never writes a router command

- **Templates only.** Four YAML templates: `queue_limit`, `failover_route`, `priority_queue` and `dns_servers`. Each has typed parameters, apply and rollback commands, and a rule for what "better" means. Gemma picks a template and fills in parameters; code renders the commands. A fifth choice, `none`, means "tell the owner, change nothing".
- **Parameters are checked.** Types, ranges and IP formats, plus rules like "a bandwidth cap is at most half the subscriber's current rate". A failed check goes back to Gemma once; a second failure gives a notify-only report.
- **Every fix is tested first.** Export the CHR config, apply, export and diff, roll back, export again. A fix passes only if it changed something and the config came back exactly. All four templates pass, on the laptop and in GitHub Actions, which boots its own CHR.
- **Names that can't collide.** Everything a fix creates is named after its incident, like `nc-1a2b3c4d`, and rollback removes only those names.
- **Old config is never touched.** We found a bug here: when a fix's `add` failed because a queue with that name existed, the rollback still ran and deleted the older queue. Now a failed fix undoes only what it created, and refuses to start if its names are taken.
- **A person approves every change,** and fixes go only to the virtual router.
- **Automatic rollback.** This one happened for real.

### The rollback that happened

During testing we injected an uplink outage. About ninety seconds in, our rule-based detector saw DNS lookups failing and called it "slow DNS". Gemma agreed, with confidence 0.75, and proposed switching the resolvers to 1.1.1.1 and 8.8.8.8. The dry run passed: the commands were valid. We approved it.

Five minutes later the workflow measured DNS lookups again: 12.0 ms before, 12.3 ms after. The template asks for a 30% drop. The workflow rolled the change back by itself, 334 seconds after the incident opened.

The fix was wrong because our detector was wrong, and the safety net caught it. We then fixed the detector (an outage now beats slow DNS) and added a test that reproduces the mistake.

## Why open models

Gemma 4 E4B runs in Ollama on a Mac mini M4 with 16 GB of memory. The laptop reaches it over the home Wi-Fi.

### Where open beat closed

A cloud model API would see every subscriber IP, every traffic rate and the router's config; with Gemma on the Mac mini, none of it leaves the building. A cloud API would be unreachable during an uplink outage, the very incident it is meant to diagnose. And it bills per token, on every incident, forever; a small ISP buys a small computer once. We did not benchmark a closed model against Gemma, so we make no claim about accuracy. For this job, those three reasons were enough.

### Thinking on or off?

Gemma 4 can "think" before it answers. We tried both on three hand-made incidents, two runs each:

| | Thinking off | Thinking on |
|---|---:|---:|
| Median time per investigation | 9.0 s | 33.6 s |
| Right cause | 6/6 | 4/6 |
| Right fix template | 5/6 | 3/6 |
| Right parameters | 5/6 | 3/6 |
| Tool calls per run (average) | 4.3 | 4.8 |

On these cases, thinking was almost four times slower and less accurate. It's a small sample, but the choice was easy: thinking off, temperature 0.2.

### How often does it get it right?

We rebuilt the inputs of our end-to-end runs and called the agent 11 times: five heavy users, three outages, three slow-DNS cases. Ten gave a valid report with the right template and parameters; two of those needed one retry. The eleventh failed twice, because Gemma kept filling in a field meant for a news tool, and fell back safely to a notify-only report. That field is now gone.

## Data

### A live home connection

The collector has run on a home connection in Pakistan since 8:30 pm on 18 October. Every 10 seconds it pings five targets (five pings each) and times DNS lookups through two resolvers: about 1,800 rounds per target by early on 19 October.

| Target | Median | 95th percentile | Average loss |
|---|---:|---:|---:|
| Home router | 3.3 ms | 15.6 ms | 0.03% |
| First upstream hop | 8.0 ms | 15.6 ms | 0.07% |
| 1.1.1.1 (ping) | 6.8 ms | 28.3 ms | 0.11% |
| 8.8.8.8 (ping) | 21.9 ms | 33.4 ms | 0.02% |
| Valve CS2 relay, Dubai (ping) | 39.1 ms | 72.6 ms | 0.11% |
| DNS lookup via 1.1.1.1 | 11.2 ms | 38.2 ms | 0.19% |
| DNS lookup via 8.8.8.8 | 34.1 ms | 67.1 ms | 0.31% |

**DNS:** lookups through 8.8.8.8 take three times as long as through 1.1.1.1: 34.1 ms against 11.2 ms at the median. The ping gap is similar (21.9 against 6.8 ms), so it looks like the network path, not the resolver. A router here using 8.8.8.8 pays about 20 ms per lookup, exactly what the `dns_servers` template fixes.

**Evenings:** the typical case didn't change: the median ping to 1.1.1.1 was 6.7 ms from 8:30 pm to 1 am and 6.8 ms after. The slow tail grew: the 95th percentile was 29.9 ms in the evening against 20.9 ms after 1 am (8.8.8.8: 34.4 against 30.4 ms). One evening, one connection, no daytime data yet.

### Simulated incidents

The demo's incidents happen on a simulated site, `sim-tower`, laid out like the virtual router: two uplinks, three subscribers and an ISP resolver. An injector writes normal data, then the incident, then a recovery. The partner also calibrated a fuller simulator with 11,819 RIPE Atlas pings from three probes on Pakistani networks; it is in the repository, unused by the demo.

## Observability with Sentry

Every incident is one Sentry trace; the trace ID is the incident ID. Each Temporal activity is a transaction in it: model requests, the dry run with its CHR API calls, apply, verify and every status change. Two lessons:

1. **Sentry's Pydantic AI integration recorded nothing.** Under `TemporalAgent`, the agent loop runs in Temporal's workflow sandbox, where the integration's hook never sees a model call. We wrapped the model instead: each Gemma request now opens a `gen_ai.chat` span inside its activity, with the model and token counts. In one heavy-user incident, Gemma made five calls: 1,136 to 1,879 input tokens, 16 to 238 output tokens, 0.6 to 14.5 seconds each.
2. **A monitoring span showed up inside incident traces.** Activities ran side by side and shared one Sentry scope. Now each gets its own, and a test proves it.

Traces (they need a Sentry login, so the screenshots are above):

- Heavy user, with `gen_ai` spans: https://aun-t9.sentry.io/explore/traces/trace/1ffec8847bc44c8f89a8b0b66a04e4f3
- The rollback: https://aun-t9.sentry.io/explore/traces/trace/5837ffbbe394489280260f42a5c969e4

## Results

End-to-end runs on the full stack: laptop, Gemma on the Mac mini, CHR and Tiger Cloud. A test script pressed Approve. Times after the first column count from when the incident opened.

**First runs, 5-minute watch:**

| Scenario | Fault to incident | Report | Dry run passed | Applied | Outcome | Key metric, before to after |
|---|---:|---:|---:|---:|---|---|
| Heavy user | 66 s | 14.6 s | 20.8 s | 29.0 s | resolved at 332 s | ping to 1.1.1.1: 56.0 to 24.9 ms |
| Uplink down | 151 s* | 14.2 s | 20.9 s | 28.4 s | resolved at 331 s | loss to 1.1.1.1: 83.3% to 0% |
| Slow DNS | 121 s | 11.8 s | 17.9 s | 24.8 s | resolved at 328 s | DNS via ISP resolver: 440.5 to 23.3 ms |
| Outage read as slow DNS | about 90 s | 18 s | 24 s | 31 s | rolled back at 334 s | DNS via 1.1.1.1: 12.0 to 12.3 ms |

**Final system, 60-second watch:**

| Scenario | Fault to incident | Report | Dry run passed | Applied | Outcome | Key metric, before to after |
|---|---:|---:|---:|---:|---|---|
| Heavy user | 50 s | 12.4 s | 19.0 s | 82.5 s** | resolved at 145 s | ping to 1.1.1.1: 40.9 to 19.4 ms |
| Uplink down | 101 s | 11.5 s | 18.1 s | 28.3 s | resolved at 91 s | loss to 1.1.1.1: 61.1% to 0% |

\* It waited out a cooldown: a new incident for the same cause can open only four minutes after the last one closed.

\*\* The script waited for the scenario to end before approving, as the dashboard advises.

A slow-DNS run in the final set opened no incident. The detector needs about two minutes of slow lookups, and that 2-minute scenario ended first. Demo scenarios now last three minutes.

## Honest limits

- **The incidents are simulated.** CHR carries no customer traffic, so a fix there can't change the measurements; the recovery is scripted. Real: the detection, Gemma's reasoning and tool calls, the router commands, the dry run and apply on a real RouterOS, the workflow, the verification, the rollback and the traces.
- **The detector is rule-based.** We built TabPFN forecasting and docs search but cut them before the deadline; they weren't reliable enough.
- **Narrow scope.** MikroTik RouterOS only, four fix templates, never a real router.
- **Small evaluation.** Eleven agent runs, six per thinking mode, a handful of end-to-end runs.

## What's next

- Run on a real router at one real site in read-only mode, then allow approved fixes.
- More causes and templates: uplink congestion and broken game routes first.
- A learned detector, once it can answer within the monitor's minute.

## Built with

- **Gemma 4** (E4B): the agent, running locally in Ollama on a Mac mini.
- **Temporal**: durable monitoring and incident workflows, with approval as a signal.
- **Sentry**: one trace per incident, with `gen_ai` spans and token counts.
- **Tiger Data**: TimescaleDB on Tiger Cloud for every metric and event.
- **GitHub Actions**: lint and tests on every push to main and every pull request, plus a CHR boot that tests every fix template.
- **Entire**: session checkpoints on more than 40 of our commits.

Also: Pydantic AI, FastAPI, MikroTik CHR in QEMU, icmplib, dnspython and uv.

Built by Aun Raza and Muhammad Anas Muqeem. Code: https://github.com/aunraza19/NetCortex
