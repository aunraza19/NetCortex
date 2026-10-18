# Secret handling and public history verification

Lead verification, 2026-10-18. No credential values are recorded in this file.

- Main's `.gitignore` is preserved, including `.env` exclusions and the deliberate
  absence of a blanket `.entire/` exclusion. `git check-ignore .env` succeeds.
- The agent did not open `.env`. A separate local masked-input PowerShell window
  wrote the credentials directly to that ignored file. Tool arguments and output
  contain no credential values. Application runtime Settings may load dotenv;
  tests construct Settings with `_env_file=None`.
- Runtime adapters unwrap SecretStr only when contacting the intended provider
  or database. Detector/provider failures use sanitized errors.
- Entire reports automatic checkpoint pushing disabled locally
  (`push_sessions=false`). Its Codex hooks need approval and no publication of
  the current coding transcript was performed. Keep credential-bearing chats
  private; replace credentials that have been published or shared through chat.
- Gitleaks 8.30.1 was installed from an official release with verified checksum.
  The initial Git branch/history scan found zero findings. A second `--all` scan
  explicitly fetched and included 18 public Entire checkpoint refs.
- The checkpoint scan returned 2,092 generic-rule occurrences. Private in-process
  classification found every captured value was a dated API feature flag adjacent
  to an OAuth beta-feature header. There were zero unclassified findings and no
  confirmed provider credentials. No allowlist suppressing provider keys was added.
- Scan reports remain ignored under `.build-check/security`; only redacted
  findings/counts were displayed. Current provider keys were not compared or printed.
- GitGuardian's PR result is checked again after pushing the rebased branch.
- A later upstream refresh increased the public checkpoint refs from 18 to 22
  and updated three existing refs. The repeated full-history/checkpoint scan
  returned 3,039 generic-rule occurrences, all privately classified as dated
  API feature flags; zero unclassified findings. No captured values were printed.
  The Gate 2 staged-content scan found zero findings, and GitGuardian passed
  before the final refresh onto Aun's newly merged CHR work.

## Codex deny-read profile

[The project profile](../.codex/config.toml) denies `.env`, dotenv variants and
credential-file paths. This follows the official [filesystem permission rules](https://learn.chatgpt.com/docs/permissions#filesystem-permissions).

The current host session was launched with unrestricted filesystem permissions.
Editing project configuration cannot retroactively enforce a sandbox boundary on
that process or its existing subagents. Start a new sandboxed Codex session with
the profile active to enforce the deny rules. Do not describe a policy instruction
or `.gitignore` entry as an operating-system read restriction. Applications run
outside the agent sandbox can load their own dotenv files normally.

Database migrations are excluded from partner setup and verification: Aun already
applied 001 on Tiger Cloud. No migration or credential rotation was performed by
this integration. Confirmed public credential leaks would require provider-side
rotation rather than merely deleting a file or ignoring a scanner finding.
