# Simgen core binding progress

Bound simgen to the merged `netcortex-core` schemas, Settings, and DB helpers. DNS slow cases now include DNS-kind lookup probes at `dns:1.1.1.1`; heavy-user evidence is continuous `SubscriberMetric` output. Fixture topology conversion retains primary, configured backup, and backhaul links and maps configured targets to core roles.

Public injection creates a UTC now-to-end scenario, takes a transaction-scoped site advisory lock, rejects overlapping simulator labels, preserves existing Site rows, and writes probe/interface/subscriber metrics plus the label in one transaction. Database load/replay use bounded inserts and Settings for credentials; mock mode remains offline.

Validation passed with the workspace environment: all 25 simgen tests and Ruff checks pass. Template expectations are checked against the installed fixes templates. Runtime Settings use shared defaults; tests isolate Settings with `_env_file=None`. Injection rejects windows over 22 hours and unknown sites before opening a connection. No live database or credentials were used. The package manifest declares its core workspace dependency; the root workspace already installs all packages with `uv sync --all-packages`.
