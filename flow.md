# NetCortex: entry points, connections and exits

This map distinguishes the partner's code from Aun's pending shared runtime.
Package `flow.md` files give exact implementation-level names and examples.
This document is updated as each component is integrated.

```mermaid
flowchart TD
    R[RIPE Atlas public API] --> S[Partner: simulator / calibration]
    S --> P[Ignored Parquet datasets + evaluation cases]
    S --> DB[(Aun: shared database contract)]
    C[Aun: live collector] --> DB
    DB --> W[Aun: monitor workflow]
    W --> D[Partner: detect]
    D --> F[Forecasts + detection evidence]
    F --> A[Aun: investigate agent]
    A --> K[Partner: search_runbook]
    MD[Official MikroTik documentation] --> K
    O[Ollama EmbeddingGemma] --> K
    K <--> DB
    A --> N[Partner: check_news]
    N --> SE[SerpApi]
    A --> X[Aun: template checker / isolated CHR]
    X --> API[Aun: FastAPI + SSE]
    A --> V[Partner: speak]
    V --> EL[ElevenLabs MP3]
    EL --> API
    API <--> UI[Partner: Next.js dashboard]
    UI --> Q{Human decision}
    Q -->|approve| IW[Aun: incident workflow]
    Q -->|reject| REJ[Rejected; no router apply]
    IW --> VERIFY[Apply on demo CHR and verify]
    VERIFY --> END[Resolved or rolled back]
    END --> API
```

## Entry and exit points

| Entry | Inputs | Connection / processing | Exit |
| --- | --- | --- | --- |
| `simgen ripe` | requested days, cache location | Discover PK probes/measurements; bounded RIPE downloads | Local raw dataset with source provenance; error on unavailable API |
| `simgen calibrate` | real baseline rows, optional exact target-role map and explicit proxy opt-in | Group statistics by target and Pakistan hour; restrict proxy transfer to public DNS ping roles | Calibration/report with coverage, defaults, source targets and transfer uncertainty |
| `simgen generate` | days, seed, scenario configuration | Seeded demand/noise and incident transforms | Probe/interface Parquet plus separate expected labels |
| `simgen replay` / `inject` | site, cause, duration, seed | Active simulator runtime; DB writes need Aun's keys/runtime agreement | Current metrics and scenario label; explicit missing-runtime/contract failure |
| `detect(site_id, window, history)` | observed shared MetricsWindow | Lag features -> TabPFN forecasts/anomaly/cause | Shared DetectionResult and approved forecast writes, or unavailable error |
| `search_runbook(query, k)` | question and result count | Ollama query embedding -> pgvector retrieval | Shared RunbookChunk objects with source URLs |
| `speak(text, lang)` | short text, en/ur | ElevenLabs with finite deadlines | MP3 bytes; empty bytes when audio unavailable |
| `check_news(provider, target)` | upstream provider/target | Recent SerpApi search | Shared NewsCheck with links; explicit unavailable summary on failure |
| Dashboard navigation | site/incident selection | Fixture transport or Aun's HTTP API | Rendered status/evidence, loading state or visible error |
| Dashboard decision | confirmed approve/reject | POST to Aun; GET authoritative incident after acknowledgement; workflow owns subsequent state | Acknowledged decision, followed by SSE/refetch; no assumed live success |
| Evaluation runner | held-out case directory and mode | Detector, then Aun's agent/checker when available | Markdown/structured results with actual measurements and pending gates |

## HTTP boundary owned by Aun

The draft API exposes `GET /sites`, `/metrics`, `/incidents`,
`/incidents/{id}`, `/incidents/{id}/voice`, `GET /stream`,
`POST /incidents/{id}/approve`, `/incidents/{id}/reject`, and
`POST /demo/scenarios`. Actual response types must come from Aun's OpenAPI.
SSE event names are `metric`, `incident.opened`, `incident.updated`, `fix.tested`
and `fix.applied`. Reconnect must refresh state; repeated event IDs must not
repeat effects. Settings reads/writes are a pending contract.

## Fixture and live exits

Fixture mode uses explicitly simulated data and transitions and displays
"Demo: replayed data". It does not apply router commands or establish provider,
model or API integration. Live mode reports a failed dependency instead of
switching to fixture data. Approval requires a valid actionable plan with a
passing CHR check and an appropriate incident state.

## Hosting and validation boundary

Render runs the dashboard's Node/Next.js server. Aun supplies the API service;
the browser does not hold database or provider secrets. Sentry receives optional
frontend monitoring when configured. CI checks offline Python/frontend behavior;
the separate CHR workflow boots a pinned router and checks authenticated REST.
Its template job runs only when Aun's actual test harness exists; boot success
alone does not establish template validity. External authentication is setup,
not an automatic claim of a working connection.
