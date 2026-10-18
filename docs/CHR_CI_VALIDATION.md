# Lead acceptance cases for the merged CHR harness

Written before delegation. The failed PR run 39152162409 used B's one-NIC boot
smoke router for Aun's newly merged three-NIC template harness. Aun's baseline
provides a static primary default route, backup/LAN interfaces, subscriber queues
and an existing DNS resolver. Without it, failover targets a DHCP-owned route,
DNS rollback fails, and subsequent baseline comparisons also fail.

1. The actual template job must run canonical `infra/chr/chr.py start`, then the
   unmodified real template harness, then canonical stop on every outcome.
   Keep the one-NIC helper only for the explicitly separate missing-harness smoke.
2. Generate a random job-only admin password, emit its GitHub mask before sharing
   it through GITHUB_ENV, and configure core-compatible CHR settings. Never write
   .env, reuse application credentials, or put password literals in YAML.
3. Retain only QEMU logs and the template JSON report. Never upload router disks,
   baselines, environment files or generated credentials.
4. Unit checks verify workflow selection and credential wiring offline. The real
   CI job must show all four templates actually applied and restored. Do not
   change assertions or skip the harness to make this green.
5. Keep core, fixes, templates and Aun's router files unchanged. This correction
   belongs to B's workflow/bootstrap wiring. Maintain .github decision/flow docs.
6. After the fix follow the user's merge sequence: clean status/save work, fetch,
   merge main, restore main's five root files including uv.lock, regenerate with
   uv lock, sync all packages, run non-live tests, commit actual changes and push
   b/workstream-b. Skip empty commits.
