"""Shared data contracts. Every package imports these; nobody redefines them.

Times are timezone-aware UTC everywhere. The UI converts to Pakistan time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID, uuid4

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EMBED_DIM = 768  # EmbeddingGemma vector size; runbook_chunks.embedding is vector(768)


# --- Vocabulary -------------------------------------------------------------


class Cause(StrEnum):
    UPLINK_CONGESTION = "uplink_congestion"
    HEAVY_USER = "heavy_user"
    UPSTREAM_DEGRADATION = "upstream_degradation"
    GAME_ROUTE_ISSUE = "game_route_issue"
    WIRELESS_INTERFERENCE = "wireless_interference"
    UPLINK_DOWN = "uplink_down"
    DNS_SLOW = "dns_slow"
    NORMAL = "normal"


class TemplateId(StrEnum):
    QUEUE_LIMIT = "queue_limit"  # limit one IP or subnet
    FAILOVER_ROUTE = "failover_route"  # backup default route with check-gateway=ping
    PRIORITY_QUEUE = "priority_queue"  # prioritise gaming and DNS traffic
    DNS_SERVERS = "dns_servers"  # switch DNS resolvers
    NONE = "none"  # no config fix; notify only


class IncidentStatus(StrEnum):
    OPEN = "open"
    AWAITING_APPROVAL = "awaiting_approval"
    APPLYING = "applying"
    VERIFYING = "verifying"
    RESOLVED = "resolved"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"


CLOSED_STATUSES = frozenset(
    {IncidentStatus.RESOLVED, IncidentStatus.ROLLED_BACK, IncidentStatus.REJECTED}
)


class Source(StrEnum):
    LIVE = "live"  # the live collector
    SIM = "sim"  # simulator: generate, replay or inject
    RIPE = "ripe"  # RIPE Atlas public measurements


class ProbeKind(StrEnum):
    ICMP = "icmp"  # rtt_ms is the ping round trip
    DNS = "dns"  # rtt_ms is the DNS lookup time; target key is "dns:<resolver>"


class TargetRole(StrEnum):
    GATEWAY = "gateway"
    UPSTREAM_HOP = "upstream_hop"
    PUBLIC_DNS = "public_dns"
    GAME_SERVER = "game_server"


class UplinkRole(StrEnum):
    PRIMARY = "primary"
    BACKUP = "backup"
    BACKHAUL = "backhaul"


class EventKind(StrEnum):
    """`events.kind`, also the SSE `event:` name on /stream."""

    METRIC = "metric"
    INCIDENT_OPENED = "incident.opened"
    INCIDENT_UPDATED = "incident.updated"
    FIX_TESTED = "fix.tested"
    FIX_APPLIED = "fix.applied"


# --- Series keys ------------------------------------------------------------

SeriesKind = Literal["probe", "iface", "subscriber"]


def series_key(kind: SeriesKind, name: str, metric: str) -> str:
    """Build a key: `probe:8.8.8.8:rtt_ms`, `probe:dns:1.1.1.1:rtt_ms`, `iface:ether1:util_pct`."""
    return f"{kind}:{name}:{metric}"


def parse_series_key(key: str) -> tuple[str, str, str]:
    """Split a series key into (kind, name, metric). The name may contain colons."""
    kind, rest = key.split(":", 1)
    name, metric = rest.rsplit(":", 1)
    if kind not in ("probe", "iface", "subscriber") or not name or not metric:
        raise ValueError(f"not a series key: {key!r}")
    return kind, name, metric


# --- Sites ------------------------------------------------------------------


class Uplink(BaseModel):
    iface: str
    role: UplinkRole
    capacity_mbps: float | None = Field(default=None, gt=0)
    gateway: str | None = None  # next-hop IP; needed by failover_route


class ProbeTarget(BaseModel):
    key: str  # value of probe_metrics.target, e.g. "8.8.8.8" or "dns:1.1.1.1"
    host: str  # what is pinged or queried
    kind: ProbeKind = ProbeKind.ICMP
    role: TargetRole


class Site(BaseModel):
    """Row of `sites`; `uplinks` and `targets` are the jsonb columns."""

    id: str
    name: str
    uplinks: list[Uplink] = []
    targets: list[ProbeTarget] = []
    subscribers: int = Field(default=0, ge=0)


# --- Metric rows ------------------------------------------------------------


class ProbeMetric(BaseModel):
    time: datetime
    site_id: str
    target: str
    kind: ProbeKind = ProbeKind.ICMP
    rtt_ms: float | None = Field(ge=0)  # response time: ICMP round trip or DNS lookup time
    jitter_ms: float | None = Field(default=None, ge=0)
    loss_pct: float = Field(ge=0, le=100)
    source: Source


class IfaceMetric(BaseModel):
    time: datetime
    site_id: str
    iface: str
    rx_bps: int = Field(ge=0)
    tx_bps: int = Field(ge=0)
    util_pct: float | None = Field(default=None, ge=0)
    drops: int = Field(default=0, ge=0)
    errors: int = Field(default=0, ge=0)
    source: Source


class SubscriberMetric(BaseModel):
    """Per-subscriber traffic (e.g. from RouterOS simple-queue counters); needed for heavy_user."""

    time: datetime
    site_id: str
    ip: str
    rx_bps: int = Field(ge=0)
    tx_bps: int = Field(ge=0)
    source: Source


PROBE_COLUMNS = tuple(ProbeMetric.model_fields)
IFACE_COLUMNS = tuple(IfaceMetric.model_fields)
SUBSCRIBER_COLUMNS = tuple(SubscriberMetric.model_fields)


def _empty_frame(columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


class MetricsWindow(BaseModel):
    """A slice of metrics for one site: DataFrames with the columns of the tables above.

    Rows have `time` <= `as_of`. Extra columns are allowed; missing ones are an error.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    as_of: datetime
    probe_metrics: pd.DataFrame = Field(default_factory=lambda: _empty_frame(PROBE_COLUMNS))
    iface_metrics: pd.DataFrame = Field(default_factory=lambda: _empty_frame(IFACE_COLUMNS))
    subscriber_metrics: pd.DataFrame = Field(
        default_factory=lambda: _empty_frame(SUBSCRIBER_COLUMNS)
    )

    @field_validator("as_of")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _has_columns(self) -> MetricsWindow:
        for name, columns in (
            ("probe_metrics", PROBE_COLUMNS),
            ("iface_metrics", IFACE_COLUMNS),
            ("subscriber_metrics", SUBSCRIBER_COLUMNS),
        ):
            missing = set(columns) - set(getattr(self, name).columns)
            if missing:
                raise ValueError(f"{name} is missing columns: {sorted(missing)}")
        return self


# --- Detector ---------------------------------------------------------------


class ForecastPoint(BaseModel):
    time: datetime  # the future time being forecast
    p10: float
    p50: float
    p90: float

    @model_validator(mode="after")
    def _ordered(self) -> ForecastPoint:
        if not self.p10 <= self.p50 <= self.p90:
            raise ValueError("forecast quantiles must satisfy p10 <= p50 <= p90")
        return self


class SeriesForecast(BaseModel):
    series_key: str  # see series_key()
    points: list[ForecastPoint]  # horizons 1..5 minutes ahead


class DetectionResult(BaseModel):
    is_anomaly: bool
    score: float = Field(ge=0, le=1)  # anomaly score
    series: list[SeriesForecast] = []
    cause_guess: Cause
    cause_confidence: float = Field(ge=0, le=1)
    evidence: list[str] = []  # short sentences, e.g. "uplink ether1 at 97% for 6 min"
    model: str  # e.g. "tabpfn-3.5"; stored in forecasts.model
    mode: Literal["cloud", "local", "mock"]


# --- Docs search and side services ------------------------------------------


class RunbookChunk(BaseModel):
    title: str
    section: str | None = None
    text: str
    source_url: str
    score: float  # higher is more relevant (e.g. 1 - cosine distance)


class NewsItem(BaseModel):
    title: str
    url: str
    published: datetime | None = None


class NewsCheck(BaseModel):
    """Result of the "is it us or them?" check.

    `available=False` means the check could not run (no key, timeout, bad response). It is
    never the same as "no outage reported"; `summary` says why.
    """

    available: bool = True
    outage_reported: bool = False
    summary: str
    items: list[NewsItem] = []


# --- Simulator --------------------------------------------------------------


class ScenarioLabel(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    site_id: str
    scenario_type: Cause
    start_at: datetime
    end_at: datetime | None = None
    affected: dict[str, Any] = {}  # e.g. {"iface": "ether1"} or {"ip": "10.0.0.42"}
    expected_cause: Cause
    expected_template: TemplateId
    expected_params: dict[str, Any] = {}
    seed: int | None = None
    source: Source = Source.SIM


# --- Agent output -----------------------------------------------------------


class IncidentReport(BaseModel):
    """What the agent returns. Validated before anything else sees it."""

    summary: str = Field(min_length=1, max_length=500)  # 1-2 plain English sentences
    likely_cause: Cause
    confidence: float = Field(ge=0, le=1)
    evidence: list[str] = []
    upstream_check: NewsCheck | None = None
    template_id: TemplateId
    template_params: dict[str, Any] = {}  # checked against the template schema by fixes
    customer_message_en: str = Field(min_length=1, max_length=320)
    customer_message_ur: str = Field(min_length=1, max_length=320)

    @model_validator(mode="after")
    def _none_has_no_params(self) -> IncidentReport:
        if self.template_id is TemplateId.NONE and self.template_params:
            raise ValueError("template 'none' takes no params")
        return self


# --- Incidents and fixes ----------------------------------------------------


class FixPlan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    incident_id: UUID
    template_id: TemplateId
    params: dict[str, Any] = {}
    commands: str = ""  # rendered from the template, never written by the model
    rollback: str = ""
    dry_run_ok: bool | None = None  # None until the CHR dry run has finished
    dry_run_log: str = ""
    decision: Literal["approved", "rejected"] | None = None
    decided_by: str | None = None
    decided_at: datetime | None = None


class Incident(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    site_id: str
    opened_at: datetime
    closed_at: datetime | None = None
    status: IncidentStatus = IncidentStatus.OPEN
    cause: Cause
    confidence: float = Field(ge=0, le=1)
    detection: DetectionResult | None = None
    report: IncidentReport | None = None
    source: Source


class Event(BaseModel):
    """Row of `events`; the API streams these over SSE (`id:` = id, `event:` = kind)."""

    id: int | None = None
    time: datetime
    kind: EventKind
    payload: dict[str, Any] = {}
