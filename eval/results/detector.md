# Detector evaluation

Mode: `mock`
Provenance: fixture: deterministic persistence/heuristic backend; no TabPFN inference
Test cases available: 80 / 80
Unavailable cases: 0

| Measure | Result |
|---|---:|
| cause_accuracy | 0.375 |
| event_precision | 1.0 |
| event_recall | 0.8857142857142857 |
| median_seconds | 0.09696915000677109 |

Precision denominator: 62
Recall denominator: 70
False alerts/site-day: 0.0 (site-day denominator 0.20833333333333334)
Detection delay: None (unavailable: runner scores one as_of snapshot per case; minute-by-minute replay is required)
Validation score count: 80
Validation unavailable cases: 0
Validation normal exposure (site-days): 0.20833333333333334
Frozen validation threshold: 0.0011706044401654952

Agent cause accuracy: None (denominator 0)
Template accuracy: None (denominator 0; unavailable: Aun investigate/template contracts are not published)
Valid parameter rate: None (denominator 0; unavailable: approved template schemas and observed parameter sources are not published)
CHR dry-run pass rate: None (denominator 0; unavailable: Aun CHR checker and machine-readable result contract are not present)

Fixture results describe only the deterministic fixture backend. They are not TabPFN accuracy claims.

## Cases

| Case | Expected cause | Predicted cause | Anomaly | Status | Seconds |
|---|---|---|---:|---|---:|
| test-case-000 | game_route_issue | normal | True | ok | 0.093 |
| test-case-001 | normal | normal | False | ok | 0.114 |
| test-case-002 | uplink_down | uplink_down | True | ok | 0.093 |
| test-case-003 | heavy_user | normal | True | ok | 0.093 |
| test-case-004 | upstream_degradation | normal | True | ok | 0.099 |
| test-case-005 | game_route_issue | normal | True | ok | 0.099 |
| test-case-006 | dns_slow | normal | False | ok | 0.096 |
| test-case-007 | dns_slow | normal | False | ok | 0.100 |
| test-case-008 | upstream_degradation | normal | True | ok | 0.098 |
| test-case-009 | upstream_degradation | normal | True | ok | 0.088 |
| test-case-010 | uplink_down | uplink_down | True | ok | 0.093 |
| test-case-011 | dns_slow | normal | False | ok | 0.104 |
| test-case-012 | upstream_degradation | normal | True | ok | 0.105 |
| test-case-013 | upstream_degradation | normal | True | ok | 0.100 |
| test-case-014 | dns_slow | normal | False | ok | 0.099 |
| test-case-015 | wireless_interference | normal | True | ok | 0.093 |
| test-case-016 | wireless_interference | normal | True | ok | 0.088 |
| test-case-017 | game_route_issue | normal | True | ok | 0.089 |
| test-case-018 | dns_slow | normal | True | ok | 0.094 |
| test-case-019 | normal | normal | False | ok | 0.099 |
| test-case-020 | game_route_issue | normal | True | ok | 0.104 |
| test-case-021 | game_route_issue | normal | True | ok | 0.093 |
| test-case-022 | wireless_interference | normal | True | ok | 0.099 |
| test-case-023 | uplink_congestion | uplink_congestion | True | ok | 0.105 |
| test-case-024 | game_route_issue | normal | True | ok | 0.099 |
| test-case-025 | uplink_congestion | uplink_congestion | True | ok | 0.091 |
| test-case-026 | game_route_issue | normal | True | ok | 0.092 |
| test-case-027 | uplink_congestion | uplink_congestion | True | ok | 0.086 |
| test-case-028 | dns_slow | normal | True | ok | 0.100 |
| test-case-029 | uplink_down | uplink_down | True | ok | 0.098 |
| test-case-030 | normal | normal | False | ok | 0.105 |
| test-case-031 | normal | normal | False | ok | 0.106 |
| test-case-032 | upstream_degradation | normal | True | ok | 0.099 |
| test-case-033 | uplink_congestion | uplink_congestion | True | ok | 0.087 |
| test-case-034 | normal | normal | False | ok | 0.101 |
| test-case-035 | heavy_user | normal | True | ok | 0.100 |
| test-case-036 | dns_slow | normal | False | ok | 0.105 |
| test-case-037 | uplink_down | uplink_down | True | ok | 0.099 |
| test-case-038 | uplink_congestion | uplink_congestion | True | ok | 0.089 |
| test-case-039 | upstream_degradation | normal | True | ok | 0.086 |
| test-case-040 | uplink_down | uplink_down | True | ok | 0.097 |
| test-case-041 | heavy_user | normal | True | ok | 0.100 |
| test-case-042 | normal | normal | False | ok | 0.099 |
| test-case-043 | heavy_user | normal | True | ok | 0.099 |
| test-case-044 | game_route_issue | normal | True | ok | 0.087 |
| test-case-045 | uplink_congestion | uplink_congestion | True | ok | 0.086 |
| test-case-046 | wireless_interference | normal | True | ok | 0.100 |
| test-case-047 | normal | normal | False | ok | 0.104 |
| test-case-048 | normal | normal | False | ok | 0.110 |
| test-case-049 | wireless_interference | normal | True | ok | 0.108 |
| test-case-050 | uplink_down | uplink_down | True | ok | 0.100 |
| test-case-051 | game_route_issue | normal | True | ok | 0.098 |
| test-case-052 | normal | normal | False | ok | 0.106 |
| test-case-053 | upstream_degradation | normal | True | ok | 0.096 |
| test-case-054 | wireless_interference | normal | True | ok | 0.088 |
| test-case-055 | wireless_interference | normal | True | ok | 0.089 |
| test-case-056 | wireless_interference | normal | True | ok | 0.099 |
| test-case-057 | heavy_user | normal | True | ok | 0.095 |
| test-case-058 | heavy_user | normal | True | ok | 0.088 |
| test-case-059 | heavy_user | normal | True | ok | 0.113 |
| test-case-060 | wireless_interference | normal | True | ok | 0.088 |
| test-case-061 | dns_slow | normal | False | ok | 0.087 |
| test-case-062 | heavy_user | normal | True | ok | 0.087 |
| test-case-063 | uplink_congestion | uplink_congestion | True | ok | 0.090 |
| test-case-064 | dns_slow | normal | False | ok | 0.087 |
| test-case-065 | upstream_degradation | normal | True | ok | 0.091 |
| test-case-066 | upstream_degradation | normal | True | ok | 0.087 |
| test-case-067 | wireless_interference | normal | True | ok | 0.087 |
| test-case-068 | heavy_user | normal | True | ok | 0.088 |
| test-case-069 | uplink_down | uplink_down | True | ok | 0.118 |
| test-case-070 | heavy_user | normal | True | ok | 0.097 |
| test-case-071 | uplink_congestion | uplink_congestion | True | ok | 0.099 |
| test-case-072 | uplink_congestion | uplink_congestion | True | ok | 0.095 |
| test-case-073 | normal | normal | False | ok | 0.094 |
| test-case-074 | uplink_down | uplink_down | True | ok | 0.098 |
| test-case-075 | uplink_congestion | uplink_congestion | True | ok | 0.088 |
| test-case-076 | uplink_down | uplink_down | True | ok | 0.088 |
| test-case-077 | game_route_issue | normal | True | ok | 0.094 |
| test-case-078 | dns_slow | normal | False | ok | 0.091 |
| test-case-079 | uplink_down | uplink_down | True | ok | 0.100 |
