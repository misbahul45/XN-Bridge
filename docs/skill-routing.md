# Skill routing

The host activates skills. XN-Bridge returns a skill name and stage reference paths; it does not replace the host skill system. The installed Codex app-server verified visibility of `xn-bridge` and `xn-career` through `skills/list`.

Canonical instructions are in `skills/`; `.agents/skills/` contains relative links to those directories so Codex can discover them without duplicated bodies. `xn-bridge` describes the coordination loop; `xn-career` composes career stages around existing search, extraction, generation and browser capabilities. Existing domain skills remain usable unchanged. These wrappers are necessary to connect existing procedures to bridge checkpoint/evidence contracts; they do not reimplement the providers.

Discovery uses name/description metadata. Activation loads `SKILL.md`; the current workflow's `next_action` names only its relevant reference. `SkillCatalog.plan_load` validates reference paths, reports skipped references and measures loaded/eager bytes. Path traversal outside a skill directory is rejected. Capability dependencies resolve through logical IDs; absent providers return degraded behavior instead of invented results.

Conflict order is explicit user selection, active workflow/stage, expected output, available capabilities and permissions, local priorities, then optional semantic disambiguation. Multi-domain requests produce separate workflow parts. Read-only parallel work is host-scheduled and subject to workflow budgets; the bridge starts no agent pool.

Metadata scanning found overlapping existing aliases; none was deleted or rewritten. The two project skills total 646 metadata bytes. In the measured career stage plans, approximately 36% of their eager instruction/reference bytes was loaded on average. This measures local reference selection, not host inference-token savings. Actual host activation by an inference model was not tested; native discoverability and stage planning were.
