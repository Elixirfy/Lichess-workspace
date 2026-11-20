# Offline feature benchmark

Run on 2026-11-08 in the workspace Python 3.12 virtual environment with the locked
dependencies. Each game has 80 synthetic legal plies, one known target player,
synthetic evals/clocks, and default K=200. No network or Stockfish is used.

Preparation is excluded; elapsed time includes `compute` reading normalized
Parquet and writing all five feature tables and the manifest. Runs were sequential.

| Games | Plies | Time (seconds) | Milliseconds/game |
|---:|---:|---:|---:|
| 250 | 20,000 | 9.037 | 36.1 |
| 500 | 40,000 | 20.663 | 41.3 |
| 1,000 | 80,000 | 43.466 | 43.5 |

The history pool fills during the first 200 games. Beyond that, doubling from
500 to 1,000 games took 2.10× the time; growth is roughly linear with fixed K.
These are wall-clock observations, not portable performance guarantees.
The regression test `tests/regression/test_performance.py` runs 300 games and asserts `compute` finishes in 20 seconds.

```bash
tilt/.venv/bin/python tilt/benchmarks/features_bench.py --games 250
tilt/.venv/bin/python tilt/benchmarks/features_bench.py --games 500
tilt/.venv/bin/python tilt/benchmarks/features_bench.py --games 1000
```
