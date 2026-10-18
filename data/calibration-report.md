# RIPE calibration report

This report summarizes downloaded public ping observations. The targets are DNS-server reachability probes; RTT is not DNS lookup latency.

## Coverage

- Observations: 11,819
- UTC coverage: 2026-10-11T00:00:26+00:00 through 2026-10-17T23:59:48+00:00
- Distinct UTC dates: 7
- Measurement IDs: 1001, 1004
- Probe IDs: 7613, 7764, 7812
- Probe ASNs: 138910, 152605, 17557

| Public ping target | Rows | Median RTT (ms) | Median loss (%) | Pakistan hours observed |
|---|---:|---:|---:|---:|
| 192.5.5.241 | 4,295 | 16.86 | 0.00 | 24/24 |
| 193.0.14.129 | 7,524 | 7.89 | 0.00 | 24/24 |

| Measurement ID | Rows | UTC dates covered | Targets |
|---:|---:|---:|---|
| 1001 | 7,524 | 7 | 193.0.14.129 |
| 1004 | 4,295 | 4 | 192.5.5.241 |

## Calibration use and gaps

- Exact configured simulator target matches: 0/5 (none).
- Public DNS role-proxy transfer: enabled.
- Explicit source targets: 192.5.5.241, 193.0.14.129.
- Proxy destination targets: 1.1.1.1, 8.8.8.8.
- Exact target calibration takes precedence. Role proxy can fill only unmatched configured public DNS targets (`1.1.1.1`, `8.8.8.8`); it never changes gateway, upstream-hop, regional-game, or DNS resolution timing.
- Role medians (only when explicitly mapped): RTT 16.325819 ms, jitter 0.05650035257903673 ms, loss 0.0%, n=11,127.
- Transfer uncertainty: These are public root-DNS-server ping paths. Their RTT, jitter, and loss are reachability proxies, not DNS lookup timing or proof of route equivalence to 1.1.1.1 or 8.8.8.8.
- The requested window covers seven UTC days. Daily failures remain in `data/ripe-baseline-summary.json`; they are not imputed.
- Failed daily requests recorded in the fetch summary: 3.
- Proxy source samples are restricted to exact observed target strings in the supplied map; provider role labels alone never authorize transfer.

Pakistan-hour target and role medians are stored in ignored `data/calibration.json`. Role transfer is off by default and requires both an exact-target role map and `--allow-role-proxy`.


Failed daily requests:
- 2026-10-13, measurement 1004: TimeoutError
- 2026-10-15, measurement 1004: TimeoutError
- 2026-10-16, measurement 1004: TimeoutError

## Explicit role-proxy statistics by Pakistan hour

| Hour PK | Median RTT (ms) | Median jitter (ms) | Median loss (%) | RTT samples |
|---:|---:|---:|---:|---:|
| 0 | 16.318362 | 0.05606639365569698 | 0.0 | 469 |
| 1 | 16.305560333333332 | 0.047581405011715525 | 0.0 | 459 |
| 2 | 16.31138066666667 | 0.048643767482473954 | 0.0 | 463 |
| 3 | 16.299233833333332 | 0.05005642229728814 | 0.0 | 454 |
| 4 | 16.305297833333334 | 0.050188871381498454 | 0.0 | 466 |
| 5 | 16.272119666666665 | 0.049732176512460764 | 0.0 | 467 |
| 6 | 16.279111999999998 | 0.048783355979951454 | 0.0 | 467 |
| 7 | 16.251087666666663 | 0.056497728904253364 | 0.0 | 466 |
| 8 | 16.26824433333333 | 0.05048028711839256 | 0.0 | 461 |
| 9 | 16.289545333333336 | 0.06299181200417098 | 0.0 | 466 |
| 10 | 16.33685266666667 | 0.06467928693175273 | 0.0 | 459 |
| 11 | 16.401758 | 0.06545249046955104 | 0.0 | 467 |
| 12 | 16.461637 | 0.06354847995368651 | 0.0 | 470 |
| 13 | 16.358806 | 0.06573944022923481 | 0.0 | 464 |
| 14 | 16.402351333333332 | 0.05947983257280477 | 0.0 | 469 |
| 15 | 16.454457666666666 | 0.056780130587692434 | 0.0 | 457 |
| 16 | 16.347939666666665 | 0.05133088025956911 | 0.0 | 457 |
| 17 | 16.332949333333335 | 0.05449381874630879 | 0.0 | 467 |
| 18 | 16.360720166666667 | 0.06418695557570152 | 0.0 | 462 |
| 19 | 16.337348666666667 | 0.06288754541242648 | 0.0 | 461 |
| 20 | 16.338292666666668 | 0.06434506354115789 | 0.0 | 458 |
| 21 | 16.3493635 | 0.06587463696598783 | 0.0 | 466 |
| 22 | 16.319249666666668 | 0.061243529851459956 | 0.0 | 467 |
| 23 | 16.325295999999998 | 0.0631476448491937 | 0.0 | 465 |