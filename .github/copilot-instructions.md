# NetCortex pull request review guidance

- Check that code stays within the owner's folders and does not clone or redefine Aun's schemas, Settings, API, SSE events, Temporal workflows, or router harness.
- For every network call, verify a finite timeout, bounded response handling, and explicit failure behavior. A fallback must not imply successful model inference, provider lookup, or router validation.
- Verify telemetry units, timestamps, source labels, subscriber privacy, forecast keys, and injection behavior against approved shared contracts. Flag guessed fields as unresolved rather than treating them as correct.
- For model and provider changes, check that offline tests cover failures and do not call real services.
- For router changes, distinguish fake/offline unit coverage from CHR integration. Only `infra/chr/test_templates.py` running on the isolated router counts as real template validation.
- Inspect template parameter validation and rollback behavior. Do not treat a successful REST status alone as proof a change was applied or improved service.
- Check that secrets, router passwords, subscriber identifiers, raw RIPE downloads, generated Parquet, and logs containing credentials are not committed or exposed to browser bundles.
- Look for concrete test evidence and accurate status claims. Do not approve documentation that claims a first user, measured results, paid/free eligibility, or a live deployment without evidence.
