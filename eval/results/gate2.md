# Gate 2 bounded provider smoke

- Status: passed
- Site: north-tower
- Provider mode: cloud
- Model: tabpfn-cloud:v3.5
- As of: 2026-10-18T17:56:11.235227+00:00
- Label ID: 938c8282-ae06-4d57-a8a0-c5941bdfa0d2
- Injected cause: uplink_congestion
- Predicted cause: uplink_down (confidence 0.4366297423839569)
- Cause matches injection: False
- Anomaly: True; score: 1.0
- Forecast rows before/after: 0 / 0

This bounded smoke establishes plumbing only; it is not an accuracy, target recall, false-alert, or warm-latency evaluation.

| Stage | Seconds |
| --- | ---: |
| provider_setup | 271.689 |
| injection | 2.642 |
| detect | 114.776 |
| total | 409.199 |

| Window | Probe rows | Interface rows | Subscriber rows |
| --- | ---: | ---: | ---: |
| history | 364 | 61 | 61 |
| current | 360 | 60 | 60 |

| Series | Points | First target | Last target |
| --- | ---: | --- | --- |
| iface:ether1:util_pct | 5 | 2026-10-18T17:57:00+00:00 | 2026-10-18T18:01:00+00:00 |
| probe:1.1.1.1:loss_pct | 5 | 2026-10-18T17:57:00+00:00 | 2026-10-18T18:01:00+00:00 |
| probe:1.1.1.1:rtt_ms | 5 | 2026-10-18T17:57:00+00:00 | 2026-10-18T18:01:00+00:00 |
| probe:dns:1.1.1.1:rtt_ms | 5 | 2026-10-18T17:57:00+00:00 | 2026-10-18T18:01:00+00:00 |

Selected probes: 1.1.1.1, dns:1.1.1.1; interface: ether1.
Only past source=sim observations enter detection. TRAIN supplies contexts;
three normal VALIDATION references and a fixed 0.7 threshold are a limited smoke setup.
The runner uses no TEST cases, performs no migration, and does not operate on home-lab.
