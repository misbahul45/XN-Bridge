# 13 — Architecture Decision Records (v2)

Verified 2026-11-17. Format: decision, context, evidence, alternatives, trade-offs, expected benefits, risks, validation, revisit conditions. Status: Accepted, Rejected, Proposed. Proposed records need owner approval before any implementation.

## ADR-001 No gateway or proxy (Accepted)
Context: 20 or more servers, large catalogs. Evidence: no requirement needs a proxy (doc 04); hooks and rules reach the same boundary inside the host (W2, W3). Alternatives: Docker MCP Gateway, 1MCP, IBM ContextForge (documented in P, not evaluated). Trade-off: no host-agnostic enforcement. Risk: a host without hooks. Validation: doc 14 phase 1. Revisit: a third host with neither hooks nor deny rules.

## ADR-002 Keep a thin local state, evidence and approval core (Accepted)
Evidence: durable state is not provided by MCP (W1, INFERRED); core is 7,784 lines of Python, two runtime dependencies, 51 MiB recorded peak RSS (R1, R8). Alternatives: Xninetzy state (policy-held, R6), host memory (conversational). Revisit if Xninetzy's approval channel is repaired and its career state is shown to cover N-01 and N-08.

## ADR-003 The host executes; the bridge records (Accepted)
Evidence: server instructions and code (R1); an MCP server cannot reach sibling servers. Trade-off: the bridge cannot validate or block sibling calls (see ADR-008).

## ADR-004 Deterministic routing; model routing off; `route_intent` demoted (Accepted for the first two, Proposed for demotion)
Evidence: deterministic 92.7 percent dev, 55 percent held-out (n=20), zero confident errors; small local models raised confident errors and latency (R8). Alternatives: semantic retrieval, model router. Validation: matched comparison with host-only activation. Revisit when a larger held-out set exists.

## ADR-005 Two skills with lazy references (Accepted)
Evidence: 648 B metadata, 6.3 KB references (R4); W5 limits. Gap: not visible to Claude Code (G-2). Follow-up needs a host-configuration change (approval required).

## ADR-006 ATS-first opportunity verification (Accepted)
Evidence: public keyless board reads exist; live Ashby read worked; ownership proof required for OPEN_VERIFIED (R8); candidates cannot use Greenhouse or Lever application endpoints (W7, W8). Alternatives: browser scraping (rejected: costlier, more brittle).

## ADR-007 Payload-bound, single-use Ed25519 approvals (Accepted)
Evidence: security tests (R7 re-run this session, R8). Limitation: authenticity requires a key the model cannot read and a host that honors the result.

## ADR-008 Host-level enforcement for external-write tools (Proposed)
Context: G-1, R19, R20, R23. Decision: add deny rules and PreToolUse hooks (managed settings where possible) that block external-write tools unless the bridge verifies a matching approval. Evidence: W2, W3 describe the mechanics; not built or tested here. Alternatives: gateway (ADR-001), manual-only (current, safe but not automating). Trade-offs: couples the system to host features; Codex needs an equivalent (tool filters, approval policy). Validation: a fixture send tool called without approval is denied; with approval it is allowed once. Revisit: if hooks cannot read tool input reliably.

## ADR-009 Browser final submission stays human (Proposed)
Context: a hook sees an element reference, not the form payload, so payload binding cannot be enforced. Decision: the model prepares and fills; the person submits. Alternatives: automated click behind an `ask` rule (prompt per click, noisy and not payload-bound). Validation: live test on a form the owner controls.

## ADR-010 Email send automation only behind batch approval and a hook (Proposed, conditional)
Preconditions: owner decision D-2 to enable a send scope; approver key created by the owner; ADR-008 validated; Gmail read OAuth done so that unknown outcomes can be reconciled. Controls: per-digest approval, expiry, daily and per-domain caps, revoke command.

## ADR-011 Catalog acceptance scoped to mapped capabilities (Proposed)
Evidence: 985 of 1,076 contracts CHANGED (R2). Decision: only tools referenced in `capabilities.toml` need acceptance; others are marked out of scope, not CHANGED. Benefit: removes an unbounded manual task.

## ADR-012 SQLite and content-addressed files (Accepted)
Evidence: concurrent writers and crash recovery tests (R8); no network service. Limitation: plaintext at rest unless the disk is encrypted.

## ADR-013 No vector store, no semantic retrieval (Accepted)
No requirement shows a retrieval problem at this scale.

## ADR-014 No multi-agent runtime (Rejected)
No measured requirement; adds coordination and attack surface.

## ADR-015 No dashboard, SaaS or paid service (Rejected)
Violates the zero-cost, local-first constraint.

## Rejected approaches (summary)
General orchestration framework; embedding router; scraping of aggregators that forbid it; programmatic submission through employer-only APIs.

## Current evidence versus design hypotheses
Evidence: ADR-002, 003, 005, 006, 007, 012. Hypotheses: ADR-004 demotion, ADR-008 to ADR-011.
