# Known limitations and next actions

| Area | Status | Boundary / next action |
|---|---|---|
| Local core and stdio lifecycle | VERIFIED_COMPLETE | Automated initialization, schema, persistence, recovery and no-listener tests |
| Codex registration and native skill discovery | VERIFIED_COMPLETE | Real installed host exercised without inference; restart interactive session to see new registration |
| Generic second domain | VERIFIED_COMPLETE | Research source collection/verification path uses the same state/evidence engine |
| Career fixture workflow | VERIFIED_COMPLETE | Local success, timeout and reconciliation only |
| Real document-provider PDF ingestion | VERIFIED_COMPLETE | Synthetic local PDF; no private CV uploaded |
| Live career discovery | PARTIALLY_COMPLETE | New public provider returned candidates and real ATS records were stored; one board 403; exact employer-to-board proof still missing in the live demo |
| Public-job and Gmail provider installation | VERIFIED_COMPLETE | Isolated pinned stdio packages; actual Codex discovery, harmless call and disabled-send rejection |
| Gmail account integration | BLOCKED | Owner OAuth client/account consent absent; AUTH_REQUIRED; no mailbox read or email send tested |
| Browser form assistance | PARTIALLY_COMPLETE | Snapshot parser/plans tested; actual browser run BLOCKED by `approval_channel_unverified` scope prerequisite |
| Consequential external execution | BLOCKED | No independently verified host-wide approval boundary; real final submission must be manual |
| Small-model routing | VERIFIED_COMPLETE evaluation | Both installed models evaluated; disabled by default due confident errors/latency |
| Arbitrary model selection in host | NOT_IMPLEMENTED | L2 returns host-reasoning escalation; no new inference provider |
| Other hosts | PARTIALLY_COMPLETE | Claude config adapter only; OpenCode/Cursor runtime adapters not implemented |
| Full catalog acceptance | PARTIALLY_COMPLETE | Expanded contract hashes quarantine old records; only five reviewed contracts accepted |
| Complete protocol notifications | PARTIALLY_COMPLETE | Native startup events plus bounded targeted host polling; tools/list_changed forwarding not exposed/assumed |
| Automatic semantic verification | NOT_IMPLEMENTED | Provenance/digests cannot establish source authenticity or claim support by themselves |
| Universal execution/schema proxy | NOT_IMPLEMENTED | Host owns sibling argument validation/execution and can bypass bookkeeping |
| Hard CPU/memory isolation | NOT_IMPLEMENTED | Cooperative memory, call, size and time bounds only; existing host sandbox retained |
| Exact host token/cache metrics | BLOCKED observability | No host inference turn in acceptance; token savings and host cache-hit rates unknown |
| Full-state one-command restore | VERIFIED_COMPLETE | Snapshot + referenced artifacts/config/encrypted approval keys restore into a new home; old grants revoked and external uncertainty reconciled. OAuth/host secrets intentionally separate. |

Existing skill alias overlap was documented and left unchanged. Tool risk heuristics, employer identity checks, public-suffix normalization and draft-fact matching are deliberately lightweight and require host review on unfamiliar data. ATS board ownership now requires a captured employer link, but that is still provenance/link validation rather than semantic authenticity proof. Approval facts supplied by the host are not authenticated user identity. DNS rebinding and same-user local filesystem tampering remain outside complete bridge enforcement. Public-provider source polling limits are advisory skill rules; no durable cross-process rate gate or automatic monitor was added.

No named research-package file was available. No real candidate CV, employer account, application submission, email send or production browser upload was used. Xninetzy code/configuration/schema were not modified. Connected-provider permission failures require repairing the host's approval channel through its supported mechanism; changing Xninetzy internals or routing around the denial is outside this implementation.
