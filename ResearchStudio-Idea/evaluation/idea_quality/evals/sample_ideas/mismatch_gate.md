# A Theory of Memorization Thresholds, and a Faster Dataloader

## Motivation
A central open question in deep learning is *when* a network transitions from generalizing to memorizing its training data — the precise sample-complexity threshold at which memorization sets in is not characterized for modern architectures, and understanding it would tell us how much data a model of a given size genuinely needs. This is a real, important, and unresolved gap with direct consequences for data curation and scaling.

## Method
1. Implement a multi-threaded data loader that prefetches batches on background workers.
2. Use memory-mapped tensor files so samples are read without full deserialization.
3. Pin host memory and overlap host-to-device copies with compute via CUDA streams.
4. Benchmark images/second on ImageNet and report the throughput speedup over the default loader.
