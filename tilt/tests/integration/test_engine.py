from pathlib import Path

import pytest

from tilt.common.engine import analyze, load_cache


@pytest.mark.skipif(not Path('/usr/games/stockfish').exists(), reason='Local Stockfish binary unavailable')
def test_real_fixed_budget_multipv_cache_and_settings_invalidation(corpus):
    data, add = corpus
    add(1)
    first = analyze(data, nodes=1000, processes=2, hash_mb=16)
    assert first['computed'] > 0
    second = analyze(data, nodes=1000, processes=2, hash_mb=16)
    assert second['computed'] == 0
    assert second['cache_hits'] == first['positions']
    cache, selected = load_cache(data)
    initial = cache['rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1']
    assert initial['best_move']
    assert initial['second_cp'] is not None or initial['second_mate'] is not None
    assert initial['engine_version'].startswith('Stockfish')
    assert initial['settings']['budget'] == {'nodes': 1000}
    assert initial['settings']['multipv'] == 2
    assert selected['threads'] == 1
    third = analyze(data, nodes=1001, processes=2, hash_mb=16)
    assert third['settings_key'] != first['settings_key']
    assert third['computed'] == first['computed']
