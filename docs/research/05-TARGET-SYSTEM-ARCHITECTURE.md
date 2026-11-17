# 05 — Target System Architecture (v2)

Verified 2026-11-17. Components are logical, not mandated services. Evidence: R1 (source), R3 (tool surface), W1 to W6.

## 1. Components and responsibilities

| ID | Component | Responsibility | Exists | Traces to |
|---|---|---|---|---|
| C1 | State engine (`store`, `workflow`, `executions`) | Workflows, stages, checkpoints, write-ahead execution records, recovery | Yes | FR-REC, FR-TRK |
| C2 | Evidence manager (`evidence`, `artifacts`) | Content-addressed raw capture, provenance, freshness, injection flags | Yes | FR-OPP, FR-CV |
| C3 | Approval service (`approval`, `security`) | Payload-bound single-use Ed25519 approvals; human CLI | Yes | FR-APR-001, FR-APR-002 |
| C4 | Capability registry (`registry`, `capabilities.toml`, `policy.toml`) | Logical capability to provider mapping, health, contract hashes, risk labels | Yes | FR-CAP, FR-BRG-002 |
| C5 | Intent router (`routing`) | Deterministic intent hints with escalation | Yes, optional | FR-BRG-003 |
| C6 | Career domain (`domains/career`) | Profile, campaign, companies, opportunities, matching, drafts, submission manifests | Yes | FR-CAR to FR-TRK |
| C7 | ATS adapter (`career/ats`) | Bounded read of Greenhouse, Lever, Ashby | Yes | FR-OPP-002 |
| C8 | Skills suite (`skills/`) | Entry skill, career skill, 9 lazy references | Yes | FR-SKL |
| C9 | Host adapters and discovery (`hosts`, `host_api`, `host_catalog`, `discovery`) | Operator audit of providers; Codex inventory | Yes, Codex-tested | FR-CAP-001 |
| C10 | Backup and restore | Full-state archive; restore revokes grants | Yes | FR-REC |
| C11 | Research domain | Second domain proving the core is generic | Yes | none in the Must set (see doc 12) |
| C12 | Host enforcement layer | Deny external-write tools that lack a valid approval | **No** | FR-APR-003 |
| X | Existing providers | Search, browser, documents, mail | Yes, reused | FR-INT-001 |

Responsibility ownership (one owner each):

| Question | Owner |
|---|---|
| Who discovers tools? | Host (native); C9 only for operator audit |
| Who selects a tool? | Host model, guided by skill and C4 resolution output |
| Who connects to sibling servers? | Host |
| Who validates sibling arguments? | Host |
| Who enforces permission? | Host rules and hooks (C12, proposed). C3 records and verifies approvals but cannot stop a direct call |
| Who handles credentials? | The provider that owns them (Gmail OAuth lives in the Gmail provider) |
| Who stores workflow state? | C1 |
| Who normalizes results? | C2 and C6 |
| Who verifies success? | Host reports; C1 requires confirmation evidence, else OUTCOME_UNKNOWN |
| Who records side effects? | C1 `execution_record` |

## 2. Diagram A — System context

```mermaid
flowchart LR
    U[Candidate] --> H[AI host: Claude Code or Codex]
    H <-->|stdio| B[XN-Bridge core]
    H <-->|host-owned| P[Existing MCP servers]
    P --> W[Company sites and public ATS boards]
    P --> M[Gmail provider]
    B --> L[(Local SQLite and artifacts)]
    U -. approves via terminal .-> B
```

## 3. Diagram B — Logical components

```mermaid
flowchart TB
    subgraph Host
      S[Skills] --> HM[Host model]
      HK[Enforcement rules and hooks: proposed]
    end
    HM <--> API[13-tool MCP surface]
    API --> C4[Registry] & C5[Router optional] & C1[State] & C2[Evidence] & C3[Approvals] & C6[Career]
    C6 --> C7[ATS adapter]
    HK -. verifies .-> C3
```

## 4. Diagram C — Dynamic tool selection

```mermaid
sequenceDiagram
    participant U as User
    participant M as Host model
    participant B as Bridge
    participant T as Sibling tool
    U->>M: request
    M->>M: skill activation by description
    M->>B: capability_resolve(web.search)
    B-->>M: provider, fallbacks, degraded text
    M->>T: call selected tool (host executes)
    T-->>M: result
    M->>B: evidence_register / execution_record
```

## 5. Diagram D — Skill activation

```mermaid
flowchart LR
    A[Metadata always loaded: 648 B for 2 skills] --> B{Description matches?}
    B -- yes --> C[SKILL.md body: about 2.1 KB]
    C --> D{Stage reached}
    D --> E[One reference file: 6.3 KB total across 9]
```

## 6. Diagram E — Career workflow

```mermaid
flowchart LR
    CV[CV] --> P[Profile] --> Cm[Campaign] --> Co[Companies] --> DV[Domain verify] --> Op[Opportunities] --> El[Eligibility] --> Ma[Match] --> Dr[Drafts] --> Rv[Human review] --> Ap[Approval] --> Sb[Submit] --> Tr[Track] --> Fu[Follow-up]
```

## 7. Diagram F — Authorization boundary (target)

```mermaid
flowchart TB
    Model[Model proposes action] --> Host[Host permission rules: deny, ask, allow]
    Host --> Hook[PreToolUse hook: verifies approval digest]
    Hook -->|valid unconsumed approval| Tool[External-write tool]
    Hook -->|none| Deny[Deny]
    User[User at terminal] -->|signs manifest| Appr[Approval store]
    Hook --> Appr
```

The model never grants. The user signs outside the model's tool surface. The hook and rules run in the host process, not in the model.

## 8. Diagram G — Failure recovery

```mermaid
stateDiagram-v2
    [*] --> PLANNED
    PLANNED --> RUNNING
    RUNNING --> STALE: process died
    STALE --> RUNNING: workflow_resume (safe reads retried)
    RUNNING --> OUTCOME_UNKNOWN: external write without confirmation
    OUTCOME_UNKNOWN --> CONFIRMED: reconcile with fresh evidence
    OUTCOME_UNKNOWN --> FAILED: reconcile shows not sent
```

## 9. Diagram H — Context and token flow

```mermaid
flowchart LR
    Raw[Raw pages and API output] --> Store[(Artifacts and evidence)]
    Store --> Sum[Bounded summary and handle]
    Sum --> Model[Model context]
    Model -->|handle| Store
    Tools[Tool definitions: host-deferred] --> Model
```

Processed outside model context: dedup, status and eligibility checks, matching, TTL checks, digest checks. Inside: summaries, drafts, decisions.

## 10. Architectural fitness functions

| Function | Threshold | Source |
|---|---|---|
| Bridge tool definition size | under 5,000 est. tokens | NFR-PER-003 |
| Always-on project skill metadata | under 300 est. tokens | NFR-PER-004 |
| No sibling call path in bridge runtime code | zero matches | FR-BRG-001 |
| Direct fixture send without approval | denied | FR-APR-003 |
| Listening sockets of the bridge process | zero | existing test |
