-- NetCortex initial schema. Every statement is idempotent, so re-running is safe.
-- All times are timestamptz (UTC).

CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS vector;

-- Sites ----------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS sites (
    id          text PRIMARY KEY,
    name        text NOT NULL,
    uplinks     jsonb NOT NULL DEFAULT '[]',   -- [{iface, role, capacity_mbps, gateway}]
    targets     jsonb NOT NULL DEFAULT '[]',   -- [{key, host, kind, role}]
    subscribers int NOT NULL DEFAULT 0,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Metrics (hypertables) --------------------------------------------------------

CREATE TABLE IF NOT EXISTS probe_metrics (
    time      timestamptz NOT NULL,
    site_id   text NOT NULL,
    target    text NOT NULL,                  -- "8.8.8.8", or "dns:1.1.1.1" for DNS lookups
    kind      text NOT NULL DEFAULT 'icmp' CHECK (kind IN ('icmp', 'dns')),
    rtt_ms    double precision,               -- NULL when every probe was lost
    jitter_ms double precision,
    loss_pct  double precision NOT NULL CHECK (loss_pct BETWEEN 0 AND 100),
    source    text NOT NULL CHECK (source IN ('live', 'sim', 'ripe'))
);
COMMENT ON COLUMN probe_metrics.rtt_ms IS
    'response time in ms: ICMP round trip, or DNS lookup time when kind = dns';
SELECT create_hypertable('probe_metrics', by_range('time'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS probe_metrics_site_time ON probe_metrics (site_id, time DESC);

CREATE TABLE IF NOT EXISTS iface_metrics (
    time     timestamptz NOT NULL,
    site_id  text NOT NULL,
    iface    text NOT NULL,
    rx_bps   bigint NOT NULL,
    tx_bps   bigint NOT NULL,
    util_pct double precision,                -- NULL when capacity is unknown
    drops    bigint NOT NULL DEFAULT 0,
    errors   bigint NOT NULL DEFAULT 0,
    source   text NOT NULL CHECK (source IN ('live', 'sim', 'ripe'))
);
SELECT create_hypertable('iface_metrics', by_range('time'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS iface_metrics_site_time ON iface_metrics (site_id, time DESC);

-- Per-subscriber traffic, so heavy_user can name the offending IP.
CREATE TABLE IF NOT EXISTS subscriber_metrics (
    time    timestamptz NOT NULL,
    site_id text NOT NULL,
    ip      text NOT NULL,
    rx_bps  bigint NOT NULL,
    tx_bps  bigint NOT NULL,
    source  text NOT NULL CHECK (source IN ('live', 'sim', 'ripe'))
);
SELECT create_hypertable('subscriber_metrics', by_range('time'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS subscriber_metrics_site_time ON subscriber_metrics (site_id, time DESC);

-- Written only by the monitor workflow; re-running a detection overwrites the same row.
CREATE TABLE IF NOT EXISTS forecasts (
    time       timestamptz NOT NULL,          -- the future time being forecast
    site_id    text NOT NULL,
    series_key text NOT NULL,                 -- probe:<target>:rtt_ms, iface:<iface>:util_pct, ...
    p10        double precision NOT NULL,
    p50        double precision NOT NULL,
    p90        double precision NOT NULL,
    model      text NOT NULL
);
SELECT create_hypertable('forecasts', by_range('time'), if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS forecasts_site_time ON forecasts (site_id, time DESC);
CREATE UNIQUE INDEX IF NOT EXISTS forecasts_key ON forecasts (site_id, series_key, model, time);

-- Incidents and fixes ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS incidents (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id    text NOT NULL,
    opened_at  timestamptz NOT NULL DEFAULT now(),
    closed_at  timestamptz,
    status     text NOT NULL DEFAULT 'open' CHECK (status IN (
                   'open', 'awaiting_approval', 'applying', 'verifying',
                   'resolved', 'rolled_back', 'rejected')),
    cause      text NOT NULL CHECK (cause IN (
                   'uplink_congestion', 'heavy_user', 'upstream_degradation', 'game_route_issue',
                   'wireless_interference', 'uplink_down', 'dns_slow', 'normal')),
    confidence double precision,
    detection  jsonb,                         -- DetectionResult
    report     jsonb,                         -- IncidentReport
    source     text NOT NULL CHECK (source IN ('live', 'sim', 'ripe'))
);
CREATE INDEX IF NOT EXISTS incidents_site_time ON incidents (site_id, opened_at DESC);
-- At most one open incident per site and cause.
CREATE UNIQUE INDEX IF NOT EXISTS incidents_one_open ON incidents (site_id, cause)
    WHERE closed_at IS NULL;

CREATE TABLE IF NOT EXISTS fix_plans (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    incident_id uuid NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    template_id text NOT NULL CHECK (template_id IN (
                    'queue_limit', 'failover_route', 'priority_queue', 'dns_servers', 'none')),
    params      jsonb NOT NULL DEFAULT '{}',
    commands    text NOT NULL DEFAULT '',
    rollback    text NOT NULL DEFAULT '',
    dry_run_ok  boolean,
    dry_run_log text NOT NULL DEFAULT '',
    decision    text CHECK (decision IN ('approved', 'rejected')),
    decided_by  text,
    decided_at  timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS fix_plans_incident ON fix_plans (incident_id);

CREATE TABLE IF NOT EXISTS incident_audio (
    incident_id uuid NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    lang        text NOT NULL CHECK (lang IN ('en', 'ur')),
    mp3         bytea NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (incident_id, lang)
);

-- Simulator labels ---------------------------------------------------------------

CREATE TABLE IF NOT EXISTS scenario_labels (
    id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    site_id           text NOT NULL,
    scenario_type     text NOT NULL,
    start_at          timestamptz NOT NULL,
    end_at            timestamptz,
    affected          jsonb NOT NULL DEFAULT '{}',
    expected_cause    text NOT NULL,
    expected_template text NOT NULL,
    expected_params   jsonb NOT NULL DEFAULT '{}',
    seed              int,
    source            text NOT NULL DEFAULT 'sim'
);
CREATE INDEX IF NOT EXISTS scenario_labels_site_time ON scenario_labels (site_id, start_at DESC);

-- Docs search ------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS runbook_chunks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_url  text NOT NULL,
    title       text NOT NULL,
    section     text,
    text        text NOT NULL,
    embedding   vector(768),
    embed_model text NOT NULL
);
CREATE INDEX IF NOT EXISTS runbook_chunks_embedding
    ON runbook_chunks USING hnsw (embedding vector_cosine_ops);

-- Events for the UI's SSE stream -------------------------------------------------

CREATE TABLE IF NOT EXISTS events (
    id      bigserial PRIMARY KEY,
    time    timestamptz NOT NULL DEFAULT now(),
    kind    text NOT NULL,                    -- incident.opened, incident.updated, fix.tested, ...
    payload jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS events_time ON events (time DESC);

-- NOTIFY carries only id and kind (payloads can exceed NOTIFY's 8 kB limit);
-- the API reads the row by id.
CREATE OR REPLACE FUNCTION notify_netcortex_event() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    PERFORM pg_notify('netcortex_events',
                      json_build_object('id', NEW.id, 'kind', NEW.kind)::text);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS events_notify ON events;
CREATE TRIGGER events_notify AFTER INSERT ON events
    FOR EACH ROW EXECUTE FUNCTION notify_netcortex_event();

-- Seed ------------------------------------------------------------------------------

-- The live collector's site. It adds the gateway and upstream hop once it finds them.
INSERT INTO sites (id, name, uplinks, targets, subscribers)
VALUES (
    'home-lab',
    'Home lab (live collector)',
    '[]',
    '[{"key": "1.1.1.1", "host": "1.1.1.1", "kind": "icmp", "role": "public_dns"},
      {"key": "8.8.8.8", "host": "8.8.8.8", "kind": "icmp", "role": "public_dns"},
      {"key": "dns:1.1.1.1", "host": "1.1.1.1", "kind": "dns", "role": "public_dns"}]',
    1
)
ON CONFLICT (id) DO NOTHING;
