"""Performance regression: feature computation on synthetic games stays within a generous bound."""
import importlib.util
from pathlib import Path

BENCH = Path(__file__).parents[2] / 'benchmarks' / 'features_bench.py'


def load_bench():
    spec = importlib.util.spec_from_file_location('features_bench', BENCH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_300_synthetic_games_finish_within_generous_bound(tmp_path):
    benchmark = load_bench().benchmark
    elapsed = benchmark(tmp_path, games=300)
    assert elapsed < 20, f'300 games x 80 plies took {elapsed:.2f}s (limit 20s)'
