# Runtime simulator integration

Added the runtime-only `sim-tower` topology to `data/sites.yaml` and the wheel
resource copy. It matches the CHR gateways, DNS resolver probes, and three
subscriber IPs while remaining outside normal fixture generation and eval
site selection.

The public injector now writes core-shaped `source=sim` normal history, the
incident interval, and 20 minutes of scripted recovery in one transaction.
Probe and 30-second metric cadences are UTC-aligned. The existing per-site
advisory lock and overlap check remain in place; writes skip existing sim
metric keys, and recovery replacement is bounded to a previous scenario's
future sim-only recovery interval. Existing Site topology is preserved.

Offline runtime acceptance and safety tests cover the topology, heavy-user,
DNS-slow and uplink-down observations, overlap rejection, deduplication,
recovery replacement bounds, and existing Site preservation. No migrations,
database credentials, or router calls were used.

Follow-up review preserved the DNS lookup target in the three original fixture
Sites, validates runtime expected parameters against the installed fix
templates, and rejects game-route or wireless-interference injection on
`sim-tower` because its configured topology has neither a game-server probe nor
a wireless backhaul.
