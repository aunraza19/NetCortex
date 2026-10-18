# CHR test router

A MikroTik Cloud Hosted Router (RouterOS 7.24.5, free license, 1 Mbit/s cap) in QEMU. Every
fix is dry-run here before a human sees it, and in the demo, approved fixes are applied
here. Nothing touches a real router.

## Setup (once)

1. Install QEMU. On Windows: `winget install SoftwareFreedomConservancy.QEMU`.
2. Put the router settings in `.env`. `CHR_PASSWORD` is a local-only value you choose; never
   commit it.

   ```
   CHR_REST_URL=http://127.0.0.1:9180
   CHR_USERNAME=admin
   CHR_PASSWORD=<random, local only>
   ```

## Use

| Windows (PowerShell) | Linux / macOS / Git Bash | What it does |
| --- | --- | --- |
| `infra\chr\start.ps1` | `sh infra/chr/start.sh` | Boot CHR. The first run downloads the pinned image (SHA-256 checked), sets the admin password on the serial console, applies `baseline.rsc` and saves `var/chr/baseline.qcow2` (about 2 min). Later starts take 30–50 s. |
| `infra\chr\reset.ps1` | `sh infra/chr/reset.sh` | Restore the baseline disk and boot again (about 50 s) |
| `infra\chr\stop.ps1` | `sh infra/chr/stop.sh` | Clean shutdown |

Then:

```bash
uv run python infra/chr/test_templates.py [--json results.json]  # dry-run all 4 templates
uv run pytest -m live packages/fixes                             # dry run + approved apply/rollback
```

REST answers on `127.0.0.1:9180` and SSH on `127.0.0.1:9122`. Both are bound to localhost only.

## The router

`baseline.rsc` sets up the router:

| Interface | Role | Address | Gateway |
| --- | --- | --- | --- |
| `ether1` | Primary uplink, QEMU user network | DHCP | Static default route via 10.0.2.2 |
| `ether2` | Backup uplink | 192.0.2.2/30 | 192.0.2.1 |
| `ether3` | LAN | 10.0.0.1/24 | — |

It also adds a simple queue for each of subscribers 10.0.0.42 and 10.0.0.57, and sets DNS to
192.0.2.53. `test_templates.py` uses sample params that fit this layout.

## Notes from setting it up (Windows 11 laptop)

- **WHPX:** with WHPX acceleration, RouterOS boots but detects no PCI NICs (virtio or e1000),
  so nothing is reachable. `chr.py` uses TCG (software emulation) on Windows. It's slower,
  but boots in about 30 s, and each template dry run takes about 6 s. On Linux it uses KVM
  when `/dev/kvm` exists.
- **Settling after boot:** RouterOS adds a default `/system keymat-provider` item a little
  after boot. `chr.py` and `test_templates.py` wait until the config stops changing, so
  export diffs stay exact.
- **Errors with HTTP 200:** `/rest/execute` returns many command errors (for example
  `invalid or unexpected argument`) as normal output. `netcortex_fixes.RouterClient` treats
  them as failures.
- **SSH fallback:** every template command runs through REST `/execute`, so no SSH fallback
  was needed.
- **CI:** the partner's bootstrap boots CHR with one NIC and no baseline, so
  `test_templates.py` can't pass on it. CI should run `chr.py start` instead (Linux, KVM or
  TCG) with a random password in the environment:

  ```bash
  export CHR_REST_URL=http://127.0.0.1:9180 CHR_USERNAME=admin
  export CHR_PASSWORD="$(python3 -c 'import secrets; print(secrets.token_urlsafe(24))')"
  echo "::add-mask::$CHR_PASSWORD"
  uv run python infra/chr/chr.py start && uv run python infra/chr/test_templates.py
  ```

  `Settings` also accepts `CHR_REST_USERNAME` and `CHR_REST_PASSWORD`, the names the
  bootstrap writes.
