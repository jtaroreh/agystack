---
name: benchmark-checklist
description: "Verify benchmark rigor and performance claims using the Seven Performance Verification Questions before reporting numbers or declaring optimizations."
disable-model-invocation: true
---

# Benchmark Checklist

Verify every performance claim, benchmark run, or optimization result before reporting numbers. Never trust a single run or guess why code got faster. Answer the Seven Performance Verification Questions directly.

## The Seven Performance Verification Questions

### 1. Limiter (Why not double?)
Ask why the improvement stopped where it did. Why not double the speedup? Name the physical bottleneck or limiter preventing 2x speedup (CPU instructions, memory bandwidth, cache line contention, disk I/O, network RTT, or thread synchronization). If you cannot name the physical limiter holding the ceiling, you do not understand the bottleneck.

### 2. Tuning (Production optimization flags)
Are production optimization flags enabled? Check compilation mode and environment flags. Confirm release mode is active (`-O2`, `-O3`, `--release`, or production build target). Verify debug assertions, sanitizers, trace logging, and developer devtools are disabled. A benchmark measured against an unoptimized debug build measures compiler accidents rather than software architecture.

### 3. Arithmetic Limits (Amdahl's law and bounds)
Calculate theoretical bounds before celebrating. Apply Amdahl's law to check the maximum theoretical speedup based on the fraction of execution time the optimized section occupied. If an optimized routine took 20% of baseline runtime, the whole system cannot speed up by 30%. Arithmetic checks prevent impossible speedup claims.

### 4. Error Checking (Correctness under benchmark)
Check failure counts and verify correctness. Confirm error states, early bailouts, or skipped validation are not miscounted as fast executions. Inspect exit codes, response bodies, and error logs across the benchmark run. Fast execution that fails silently or returns early is a defect, not a performance win.

### 5. Reproduction (Variance and sample size)
Mandate running at least five runs. Record variance and median, not a single lucky run. Single-iteration spikes distort numbers through CPU frequency scaling, cold caches, background kernel interrupts, or JIT warm-up cycles. Discard cold starts if measuring steady state, report the median and standard deviation across five or more runs, and verify the gain clears noise.

### 6. Relevance (Microbenchmark versus whole-system)
Compare microbenchmark relevance to the whole-system realistic workload. Microbenchmarks isolate functions but miss cache eviction, memory pressure, context switches, and concurrent lock contention. Verify that microbenchmark improvements translate to end-to-end user-visible latency or throughput under realistic production data sizes and traffic shapes.

### 7. Lazy Execution (Confirm actual work executed)
Confirm the measured work actually executed. Ensure the compiler, optimizer, or runtime did not eliminate dead code. Prevent dead code elimination by consuming or asserting on benchmark outputs. Confirm asynchronous operations actually completed rather than leaving unmeasured deferred computation pending on an unpolled event loop.
