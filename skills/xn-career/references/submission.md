# Submission (EXTERNAL_WRITE)
1. `submission.prepare` builds the manifest: destination, content digests, attachments, the user's declarations. It refuses a target outside the company's verified domain or the listing's apply host.
2. Call `bridge_status`. If `unattended_external_writes` is true and `external_writes_stopped` is false, go to step 4. Otherwise continue with step 3.
3. Attended: `approval_prepare(payload_ref="entity:<manifest_id>", target=<url>)`. Tell the user to run `xnbridge approve <approval_id>` themselves. After the grant: `execution_record(op=begin, approval_id, target)`.
4. Unattended (the owner enabled it): `execution_record(op=begin, target=<url>, idempotency_key=<new key>)` with no approval_id. The bridge still blocks duplicates, applies the daily and per-destination caps and honors the stop file. If it refuses with a duplicate, limit or policy error, stop and report it; do not look for another route.
5. Perform the single final action with the host tool, then `execution_record(op=finish)` with confirmation evidence.
6. No confirmation evidence or a timeout means OUTCOME_UNKNOWN. Do not retry. `workflow_resume`, tell the user, then `op=reconcile` once fresh evidence exists.
Unattended mode never covers CAPTCHA, login, or consent and identity declarations; those stay with the person.
