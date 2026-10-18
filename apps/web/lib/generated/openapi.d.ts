export interface paths {
  "/health": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Health */
    get: operations["health_health_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/sites": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Sites */
    get: operations["sites_sites_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/metrics": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Metrics */
    get: operations["metrics_metrics_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/incidents": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Incidents */
    get: operations["incidents_incidents_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/incidents/{incident_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** Incident */
    get: operations["incident_incidents__incident_id__get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/incidents/{incident_id}/approve": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Approve */
    post: operations["approve_incidents__incident_id__approve_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/incidents/{incident_id}/reject": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Reject */
    post: operations["reject_incidents__incident_id__reject_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/demo/scenarios": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** Inject Scenario */
    post: operations["inject_scenario_demo_scenarios_post"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/stream": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /**
     * Stream
     * @description Server-sent events: incident.opened, incident.updated, fix.tested, fix.applied.
     *     Reconnect with Last-Event-ID to replay what was missed.
     */
    get: operations["stream_stream_get"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    /** Accepted */
    Accepted: {
      /**
       * Incident Id
       * Format: uuid
       */
      incident_id: string;
      /** Decision */
      decision: string;
      /** Note */
      note: string;
    };
    /** Band */
    Band: {
      /**
       * Time
       * Format: date-time
       */
      time: string;
      /** P10 */
      p10: number;
      /** P50 */
      p50: number;
      /** P90 */
      p90: number;
    };
    /**
     * Cause
     * @enum {string}
     */
    Cause:
      | "uplink_congestion"
      | "heavy_user"
      | "upstream_degradation"
      | "game_route_issue"
      | "wireless_interference"
      | "uplink_down"
      | "dns_slow"
      | "normal";
    /** Decision */
    Decision: {
      /**
       * Decided By
       * @default owner
       */
      decided_by: string;
    };
    /** DetectionResult */
    DetectionResult: {
      /** Is Anomaly */
      is_anomaly: boolean;
      /** Score */
      score: number;
      /**
       * Series
       * @default []
       */
      series: components["schemas"]["SeriesForecast"][];
      cause_guess: components["schemas"]["Cause"];
      /** Cause Confidence */
      cause_confidence: number;
      /**
       * Evidence
       * @default []
       */
      evidence: string[];
      /** Model */
      model: string;
      /**
       * Mode
       * @enum {string}
       */
      mode: "cloud" | "local" | "mock";
    };
    /**
     * Event
     * @description Row of `events`; the API streams these over SSE (`id:` = id, `event:` = kind).
     */
    Event: {
      /** Id */
      id?: number | null;
      /**
       * Time
       * Format: date-time
       */
      time: string;
      kind: components["schemas"]["EventKind"];
      /**
       * Payload
       * @default {}
       */
      payload: {
        [key: string]: unknown;
      };
    };
    /**
     * EventKind
     * @description `events.kind`, also the SSE `event:` name on /stream.
     * @enum {string}
     */
    EventKind:
      | "metric"
      | "incident.opened"
      | "incident.updated"
      | "fix.tested"
      | "fix.applied";
    /** FixPlan */
    FixPlan: {
      /**
       * Id
       * Format: uuid
       */
      id?: string;
      /**
       * Incident Id
       * Format: uuid
       */
      incident_id: string;
      template_id: components["schemas"]["TemplateId"];
      /**
       * Params
       * @default {}
       */
      params: {
        [key: string]: unknown;
      };
      /**
       * Commands
       * @default
       */
      commands: string;
      /**
       * Rollback
       * @default
       */
      rollback: string;
      /** Dry Run Ok */
      dry_run_ok?: boolean | null;
      /**
       * Dry Run Log
       * @default
       */
      dry_run_log: string;
      /** Decision */
      decision?: ("approved" | "rejected") | null;
      /** Decided By */
      decided_by?: string | null;
      /** Decided At */
      decided_at?: string | null;
    };
    /** ForecastPoint */
    ForecastPoint: {
      /**
       * Time
       * Format: date-time
       */
      time: string;
      /** P10 */
      p10: number;
      /** P50 */
      p50: number;
      /** P90 */
      p90: number;
    };
    /** HTTPValidationError */
    HTTPValidationError: {
      /** Detail */
      detail?: components["schemas"]["ValidationError"][];
    };
    /** Health */
    Health: {
      /**
       * Status
       * @default ok
       */
      status: string;
      /** Demo Mode */
      demo_mode: boolean;
    };
    /** Incident */
    Incident: {
      /**
       * Id
       * Format: uuid
       */
      id?: string;
      /** Site Id */
      site_id: string;
      /**
       * Opened At
       * Format: date-time
       */
      opened_at: string;
      /** Closed At */
      closed_at?: string | null;
      /** @default open */
      status: components["schemas"]["IncidentStatus"];
      cause: components["schemas"]["Cause"];
      /** Confidence */
      confidence: number;
      detection?: components["schemas"]["DetectionResult"] | null;
      report?: components["schemas"]["IncidentReport"] | null;
      source: components["schemas"]["Source"];
    };
    /** IncidentDetail */
    IncidentDetail: {
      incident: components["schemas"]["Incident"];
      fix_plan: components["schemas"]["FixPlan"] | null;
      /** Timeline */
      timeline: components["schemas"]["Event"][];
    };
    /**
     * IncidentReport
     * @description What the agent returns. Validated before anything else sees it.
     */
    IncidentReport: {
      /** Summary */
      summary: string;
      likely_cause: components["schemas"]["Cause"];
      /** Confidence */
      confidence: number;
      /**
       * Evidence
       * @default []
       */
      evidence: string[];
      upstream_check?: components["schemas"]["NewsCheck"] | null;
      template_id: components["schemas"]["TemplateId"];
      /**
       * Template Params
       * @default {}
       */
      template_params: {
        [key: string]: unknown;
      };
      /** Customer Message En */
      customer_message_en: string;
      /** Customer Message Ur */
      customer_message_ur: string;
    };
    /**
     * IncidentStatus
     * @enum {string}
     */
    IncidentStatus:
      | "open"
      | "awaiting_approval"
      | "applying"
      | "verifying"
      | "resolved"
      | "rolled_back"
      | "rejected";
    /** IncidentSummary */
    IncidentSummary: {
      /**
       * Id
       * Format: uuid
       */
      id: string;
      /** Site Id */
      site_id: string;
      /**
       * Opened At
       * Format: date-time
       */
      opened_at: string;
      /** Closed At */
      closed_at: string | null;
      status: components["schemas"]["IncidentStatus"];
      /** Cause */
      cause: string;
      /** Confidence */
      confidence: number | null;
      /** Summary */
      summary?: string | null;
      /** Template Id */
      template_id?: string | null;
    };
    /**
     * NewsCheck
     * @description Result of the "is it us or them?" check.
     *
     *     `available=False` means the check could not run (no key, timeout, bad response). It is
     *     never the same as "no outage reported"; `summary` says why.
     */
    NewsCheck: {
      /**
       * Available
       * @default true
       */
      available: boolean;
      /**
       * Outage Reported
       * @default false
       */
      outage_reported: boolean;
      /** Summary */
      summary: string;
      /**
       * Items
       * @default []
       */
      items: components["schemas"]["NewsItem"][];
    };
    /** NewsItem */
    NewsItem: {
      /** Title */
      title: string;
      /** Url */
      url: string;
      /** Published */
      published?: string | null;
    };
    /** Point */
    Point: {
      /**
       * Time
       * Format: date-time
       */
      time: string;
      /** Value */
      value: number | null;
    };
    /** ScenarioLabel */
    ScenarioLabel: {
      /**
       * Id
       * Format: uuid
       */
      id?: string;
      /** Site Id */
      site_id: string;
      scenario_type: components["schemas"]["Cause"];
      /**
       * Start At
       * Format: date-time
       */
      start_at: string;
      /** End At */
      end_at?: string | null;
      /**
       * Affected
       * @default {}
       */
      affected: {
        [key: string]: unknown;
      };
      expected_cause: components["schemas"]["Cause"];
      expected_template: components["schemas"]["TemplateId"];
      /**
       * Expected Params
       * @default {}
       */
      expected_params: {
        [key: string]: unknown;
      };
      /** Seed */
      seed?: number | null;
      /** @default sim */
      source: components["schemas"]["Source"];
    };
    /** ScenarioRequest */
    ScenarioRequest: {
      /**
       * Site Id
       * @default sim-tower
       */
      site_id: string;
      scenario_type: components["schemas"]["Cause"];
      /**
       * Duration Min
       * @default 5
       */
      duration_min: number;
      /** Seed */
      seed?: number | null;
    };
    /** Series */
    Series: {
      /** Series Key */
      series_key: string;
      /** Points */
      points: components["schemas"]["Point"][];
      /** Forecast */
      forecast: components["schemas"]["Band"][];
    };
    /** SeriesForecast */
    SeriesForecast: {
      /** Series Key */
      series_key: string;
      /** Points */
      points: components["schemas"]["ForecastPoint"][];
    };
    /** SiteHealth */
    SiteHealth: {
      /** Id */
      id: string;
      /** Name */
      name: string;
      /**
       * Health
       * @enum {string}
       */
      health: "ok" | "degraded" | "down" | "unknown";
      /** Worst Rtt Ms */
      worst_rtt_ms?: number | null;
      /** Max Loss Pct */
      max_loss_pct?: number | null;
      /** Uplink Util Pct */
      uplink_util_pct?: number | null;
      /**
       * Open Incidents
       * @default 0
       */
      open_incidents: number;
      /** Updated At */
      updated_at?: string | null;
      /**
       * Uplinks
       * @default []
       */
      uplinks: {
        [key: string]: unknown;
      }[];
    };
    /**
     * Source
     * @enum {string}
     */
    Source: "live" | "sim" | "ripe";
    /**
     * TemplateId
     * @enum {string}
     */
    TemplateId:
      | "queue_limit"
      | "failover_route"
      | "priority_queue"
      | "dns_servers"
      | "none";
    /** ValidationError */
    ValidationError: {
      /** Location */
      loc: (string | number)[];
      /** Message */
      msg: string;
      /** Error Type */
      type: string;
      /** Input */
      input?: unknown;
      /** Context */
      ctx?: Record<string, never>;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  health_health_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Health"];
        };
      };
    };
  };
  sites_sites_get: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SiteHealth"][];
        };
      };
    };
  };
  metrics_metrics_get: {
    parameters: {
      query: {
        site_id: string;
        /** @description e.g. probe:8.8.8.8:rtt_ms */
        series: string[];
        from?: string | null;
        to?: string | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Series"][];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  incidents_incidents_get: {
    parameters: {
      query?: {
        status?: components["schemas"]["IncidentStatus"] | null;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["IncidentSummary"][];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  incident_incidents__incident_id__get: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        incident_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["IncidentDetail"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  approve_incidents__incident_id__approve_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        incident_id: string;
      };
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": components["schemas"]["Decision"] | null;
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Accepted"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  reject_incidents__incident_id__reject_post: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        incident_id: string;
      };
      cookie?: never;
    };
    requestBody?: {
      content: {
        "application/json": components["schemas"]["Decision"] | null;
      };
    };
    responses: {
      /** @description Successful Response */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Accepted"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  inject_scenario_demo_scenarios_post: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ScenarioRequest"];
      };
    };
    responses: {
      /** @description Successful Response */
      201: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ScenarioLabel"];
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
  stream_stream_get: {
    parameters: {
      query?: never;
      header?: {
        "last-event-id"?: number | null;
      };
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Successful Response */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": unknown;
        };
      };
      /** @description Validation Error */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["HTTPValidationError"];
        };
      };
    };
  };
}
