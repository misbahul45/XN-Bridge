# Performance results — 17 November 2026

Reproduce with `scripts/eval_routing.py` and `scripts/bench_workloads.py --kill-cycles 10`. Local outputs are `bench-out/routing-current.json`, `bench-out/performance.json`, and `bench-out/codex-host.json`. These are single-laptop observations, not general performance guarantees. Benchmarks ran alongside acceptance tests, so timings include ordinary scheduling/disk noise.

## Routing comparison

The same fixed 82-case development and 20-case held-out datasets cover explicit, ambiguous, multi-domain, continuation, missing-information, conflicting, permission, unavailable-provider and paraphrased requests. Accuracy includes correct escalation decisions; it is not autonomous task-completion accuracy.

| Cascade | Set | Accuracy | Confident errors | Model calls | Total routing latency |
|---|---|---:|---:|---:|---:|
| Deterministic + host escalation | 82 dev | 92.7% | 0 | 0 | 20.2 ms |
| Deterministic + host escalation | 20 held-out | 55.0% | 0 | 0 | 3.6 ms |
| + Qwen 2.5 1.5B | 82 dev | 86.6% | 11 | 18 | 24.64 s |
| + Qwen 2.5 1.5B | 20 held-out | 70.0% | 6 | 11 | 12.87 s |
| + Gemma 3 4B | 82 dev | 85.4% | 8 | 18 | 182.58 s |
| + Gemma 3 4B | 20 held-out | 90.0% | 2 | 11 | 111.08 s |

Deterministic p50/p95: 0.16/0.41 ms on development, 0.18/0.25 ms on held-out. It escalated 18 and 11 cases respectively, including safely missed paraphrases. Qwen averaged 1.37/1.17 s per local model call; Gemma 10.14/10.10 s. No invalid structured model outputs were observed in these runs, but valid structure did not guarantee correct classification.

Actual Ollama counters: Qwen used **6,567 input / 302 output tokens** over 29 calls; Gemma **7,050 / 285** over 29 calls. These are runtime `prompt_eval_count`/`eval_count`, not tokenizer estimates. Approximate measured Ollama process RSS after runs was 1,152–1,154 MiB for Qwen and 3,635–3,659 MiB for Gemma. No GPU acceleration is claimed. Dedicated small-model routing stays **disabled**: it increased confidently wrong routes and latency despite improving held-out recognition.

## Coordination workload

| Workload | Measured result |
|---|---|
| Capability lookup, 300 iterations | p50 1.725 ms; p95 2.293 ms |
| Workflow creation, 100 iterations | p50 4.609 ms; p95 7.691 ms |
| Checkpoint, 200 iterations | p50 4.989 ms; p95 8.307 ms |
| Evidence capture, 100 iterations | p50 9.755 ms; p95 44.236 ms |
| Deduplicate 500 company candidates | 77.8 ms; 400 added / 100 merged |
| Parse/classify 300 postings | 249.7 ms; 100 internships retained |
| Match 100 opportunities | 59.1 ms |
| Prepare two draft artifacts | 58.6 ms; zero model calls |
| Parse fixture form snapshot, 30 iterations | p50 17.710 ms; p95 58.750 ms |
| Workflow resume, 30 iterations | p50 0.795 ms; p95 1.219 ms |
| Local latency workload resources | 51 MiB peak process RSS; 1.92 s CPU time |
| Four concurrent writers / 160 checkpoints | 0.95 s wall; p50 1.121 ms / p95 15.562 ms; integrity passed |
| Crash recovery | 10/10 cycles recovered; 210 interrupted attempts flagged; p50 106.958 ms / p95 300.245 ms |
| Real Codex host acceptance | 1.807 s for setup/discovery/skill checks and five bridge calls; zero inference calls |

The company/posting/form workloads use synthetic fixtures, not live recruiting latency. Document preparation measures deterministic draft skeletons, not PDF rendering or cover-letter inference. CPU time/RSS refer to the local benchmark process; they exclude independently launched providers and model runners. The form measurement is snapshot parsing; actual browser inspection was blocked and has no claimed live latency.

## Context/output comparison

The identical synthetic 300-posting board is 243,700 UTF-8 bytes. Its SUMMARY response is 349 bytes; DETAIL is 327 bytes; RAW_REFERENCE is 464 bytes and points to local raw storage. Each mode starts with an independent identical workflow. DETAIL can be smaller because SUMMARY adds a disclosure hint. Raw records remain available by reference.

Discovery measured 1,296,454 UTF-8 bytes for the name/description/input-schema projection of 1,008 tools. This excludes protocol framing, output schemas and host-specific metadata. Nine compact capability lookups in the empty-catalog fixture totaled 4,087 bytes; this is an interface-size comparison, not measured native-host savings, and excludes subsequently loaded selected-tool schemas. Career stage references averaged approximately 36% of eager instruction/reference bytes.

Host input/output tokens, actual tool-definition injection overhead, native cache hits, stronger-model escalation costs, and total inference cost per successful live task are **UNAVAILABLE**. Any byte/4 values in raw benchmark JSON are explicitly rough estimates and are not presented as actual token consumption. No percentage of host token savings is claimed. Fixture policy assertions passed; production policy-violation rate and real-world career success rate are unknown.
