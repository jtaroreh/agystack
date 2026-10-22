---
name: principle-explain-the-number
description: "Apply when reporting performance numbers, benchmarks, or latency comparisons. Name the physical bottleneck and hardware/kernel root cause rather than guessing from code."
disable-model-invocation: true
---

# Explain the Number

When reporting performance numbers, microbenchmarks, or latency comparisons, name the bottleneck and physical cause rather than guessing from code.

**Trigger:** Activates on performance reports, benchmarks, latency comparisons, and optimization proposals.

**Why:** A number without a physical mechanism is a coincidence. Inferring performance wins by reading code lines leads to false attribution. Compilers reorder instructions, operating systems buffer I/O, and CPU caches mask algorithmic changes. If you cannot explain the hardware or kernel reason why a number changed, you cannot guarantee the win persists in production.

**Rule:** Every reported performance delta must specify:
1. The exact metric measured and baseline number.
2. The measured post-change number and verified delta.
3. The physical mechanism that caused the shift (reduced memory bandwidth, eliminated disk I/O, lowered cache line contention, pruned serialization overhead, or removed thread synchronization locks).

Do not say "the loop is cleaner so it runs faster". Identify what hardware resource was spared:
- Memory subsystem: Cache hit rates, allocation churn, memory bandwidth saturation, or pointer dereference stalls.
- I/O and kernel: System call frequency, file descriptor polling, socket buffer saturation, or context switch volume.
- CPU pipeline: Branch prediction mispredictions, vectorized SIMD instruction saturation, or instruction cache pressure.
- Concurrency: Mutex lock contention, false sharing across cache lines, thread pool exhaustion, or atomic contention.

If profiling data or hardware counters cannot confirm the mechanism, label the explanation as an unverified hypothesis and measure the counter before declaring success.
