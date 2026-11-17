# Decision routing

Layer 0 uses explicit commands, active workflow continuation, closed intent rules, conflict checks, dynamic slots and exact capability requests. These paths use zero model calls. Unknown or ambiguous requests return candidates and `needs_host_reasoning`; they are not silently forced into a domain.

Layer 1 is an optional classifier using the installed loopback Ollama runner. It can return only an existing intent and a string reason; additional fields and invented intent IDs are rejected. The bridge validates the result and recomputes required capabilities and approval policy from local contracts. Memory pressure and timeout guards skip/fail the optional classifier safely. Layer 2 is an escalation instruction for the existing host model, not an independent cloud request or automatic stronger-model selection.

Both installed small models were evaluated on 82 development and 20 held-out requests. Qwen and Gemma reduced escalation but introduced confidently wrong routes and higher latency. The reproducible evidence is in [performance results](performance-results.md). Therefore `[routing] l1_enabled = false` remains the default. No new model was downloaded and no custom training was attempted.

Resource adaptation is conservative: a local endpoint must be loopback, minimum available memory is checked, and per-call timeouts are bounded. GPU acceleration and an optimal CPU scheduling policy are not claimed. RSS/memory guards are cooperative checks, not OS-enforced CPU or memory isolation.

Heavy bridge operations also check normalized system load, process RSS and available RAM before work. Configured pressure returns RESOURCE_PRESSURE; simulated high-load, high-RSS and low-memory cases are tested. System load is not an exact CPU-utilization measurement.

Run `scripts/eval_routing.py --models` for deterministic-only evaluation, or omit that option to compare the already-installed models. Reported local token counts come from Ollama's runtime fields. Host L2 tokens are unavailable because the evaluation does not invoke the host model. Model confidence is not treated as calibrated probability and cannot approve actions.
