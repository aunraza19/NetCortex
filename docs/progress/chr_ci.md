# CHR template CI correction

The template job now uses the canonical `infra/chr/chr.py start` lifecycle so
the real four-template harness sees the repository's three-NIC baseline. The
missing-harness smoke job continues to use the standalone one-NIC bootstrap.
The template job generates and masks a random job-only password before writing
its CHR settings to `GITHUB_ENV`, invokes the unmodified harness with a JSON
report destination, uploads only the QEMU log and report, and always requests
canonical cleanup.

The offline acceptance tests cover workflow ordering, the always-run cleanup,
artifact allowlisting, and credential masking/environment-file output. No local
QEMU, router, or credentialed service was used for this change; the real CHR
template job remains the external integration check.
