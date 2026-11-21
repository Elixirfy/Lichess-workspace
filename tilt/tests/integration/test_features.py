from copy import deepcopy
import json

import pandas as pd
import pytest

from tilt.data import storage
from tilt.features.features import compute, move_features, windows_and_events, robust, aggregate
from tilt.data.normalize import api_game


def test_think_times_first_moves_increment_final_mate_and_clock_fraction(api_raw):
    game, moves = api_game(api_raw)
    rows, _ = move_features(game, moves, {})
    assert rows[0]['think_seconds'] is None and rows[1]['think_seconds'] is None
    assert rows[0]['unclocked_first_move']
    assert rows[2]['think_seconds'] == 4  # 180 - 178 + 2
    assert rows[-1]['think_seconds'] == 2  # terminal move has no increment
    assert rows[2]['clock_fraction'] == 1  # before this move, own clock still 180
    assert rows[-1]['eval_after_cp'] == 1000  # mate=0 with Black to move means White wins
    assert rows[1]['eval_before_cp'] == -20  # mover's POV for Black
    assert rows[2]['material_balance'] == 0
    assert rows[-1]['capture'] and rows[-1]['check']
    assert rows[0]['legal_moves'] == 20
    assert rows[0]['best_second_gap_cp'] is None
    assert rows[0]['eval_before_source'] == 'lichess_legacy_initial'
    assert rows[5]['just_missed_win'] or rows[5]['just_blundered']


def test_gifted_clock_not_fabricated_as_zero_time(api_raw):
    raw = deepcopy(api_raw)
    raw['clocks'][2] = 19000
    game, moves = api_game(raw)
    rows, _ = move_features(game, moves, {})
    assert rows[2]['clock_anomaly']
    assert rows[2]['think_seconds'] is None


def test_clock_missing_fraction_structural_moves_and_real_gaps(api_raw):
    game, moves = api_game(api_raw)
    rows, _ = move_features(game, moves, {})
    own = [r for r in rows if r['color'] == 'white']
    assert aggregate(own)['clock_missing_fraction'] == 0
    assert aggregate(own[:1])['clock_missing_fraction'] is None
    # One actual missing clock and one observed premove: only two eligible
    # intervals remain, one missing. First own move must never create 1/N.
    short = deepcopy(own[:4])
    short[1]['think_seconds'] = None
    short[2]['think_seconds'] = 0
    assert aggregate(short)['clock_missing_fraction'] == .5
    assert aggregate(short[:1] + [short[2]])['clock_missing_fraction'] is None
    short[1]['think_seconds'] = float('nan')
    assert aggregate(short)['clock_missing_fraction'] == .5


def test_clock_missing_fraction_zero_increment_premove(api_raw):
    raw = deepcopy(api_raw)
    raw['clock']['increment'] = 0
    raw['clocks'][2] = raw['clocks'][0]
    game, moves = api_game(raw)
    rows, _ = move_features(game, moves, {})
    own = [r for r in rows if r['color'] == 'white']
    assert own[1]['think_seconds'] == 0
    assert aggregate(own)['clock_missing_fraction'] == 0


def test_engine_best_second_and_missing_evals(api_raw):
    raw = deepcopy(api_raw)
    raw.pop('analysis')
    game, moves = api_game(raw)
    fen = moves[0]['fen_before']
    cache = {fen: {'cp': 20, 'mate': None, 'second_cp': 10, 'second_mate': None, 'best_move': 'e2e4'},
             moves[0]['fen_after']: {'cp': 18, 'mate': None}}
    rows, _ = move_features(game, moves, cache)
    assert rows[0]['best_second_gap_cp'] == 10
    assert rows[0]['differs_from_best'] is False
    assert rows[0]['cpl'] == 2
    assert rows[2]['cpl'] is None
    assert rows[2]['judgement'] is None


def test_no_future_or_overlapping_game_influences_any_earlier_feature(corpus):
    data, add = corpus
    add(1, start=100000, end=160000)
    add(2, start=200000, end=280000, error=True)
    add(3, start=250000, end=330000)
    compute(data, min_prior_games=1)
    before = {name: pd.read_parquet(data/'processed' / 'features'/f'{name}.parquet').sort_values(
        ['game_id','player'] + (['ply'] if name=='moves' else [])).reset_index(drop=True) for name in ('games','moves')}
    alice = before['games'][before['games'].player == 'alice'].set_index('game_id')
    assert alice.loc['game0001', 'baseline_speed_games'] == 0
    assert pd.isna(alice.loc['game0001', 'behavioral_deviation_score'])
    assert alice.loc['game0003', 'baseline_speed_games'] == 1  # game 2 hasn't ended
    assert alice.loc['game0003', 'baseline_latest_end_ms'] < alice.loc['game0003', 'start_ms']
    add(4, start=500000, end=560000, error=True)
    compute(data, min_prior_games=1)
    for name, expected in before.items():
        after = pd.read_parquet(data/'processed' / 'features'/f'{name}.parquet')
        after = after[after.game_id != 'game0004'].sort_values(
            ['game_id','player'] + (['ply'] if name=='moves' else [])).reset_index(drop=True)
        pd.testing.assert_frame_equal(expected, after)


def test_minimum_history_same_speed_and_unknown_end(corpus, api_raw):
    data, add = corpus
    add(1)
    raw = deepcopy(api_raw)
    raw.update(id='unknown1', createdAt=200000, lastMoveAt=220000, status='resign',
               moves='e4 e5', analysis=[{'eval':15},{'eval':15}], clocks=[])
    game, moves = api_game(raw, observed_ms=9999999)
    storage.append(data, [game], moves)
    add(3, start=300000, end=360000)
    compute(data, min_prior_games=2)
    frame = pd.read_parquet(data/'processed/features/games.parquet')
    row = frame[(frame.player=='alice') & (frame.game_id=='game0003')].iloc[0]
    assert row.baseline_speed_games == 1
    assert pd.isna(row.deviation_mean_cpl_z)
    assert row.session_id == frame[(frame.player=='alice') & (frame.game_id=='game0001')].iloc[0].session_id


def test_robust_zero_mad_missingness_and_frequency():
    history = [{'game_id':str(i),'x':2} for i in range(5)]
    out = robust({'x':4}, history, {'x':1}, 5)
    assert out['baseline_x_median'] == 2
    assert out['baseline_x_mad'] == 0
    assert out['deviation_x_z'] == 2
    assert out['historical_x_similar_fraction'] == 0
    assert out['behavioral_deviation_score'] == 20
    assert robust({'x':4},history,{'x':1},6)['behavioral_deviation_score'] is None


def test_windows_events_are_explicitly_retrospective(api_raw):
    game, moves = api_game(api_raw)
    rows, _ = move_features(game, moves, {})
    own = [r for r in rows if r['player']=='bob']
    windows, events = windows_and_events(own, 4, normal_cpl=20)
    for row in windows:
        assert row['available_after_ply'] == row['end_ply']
        assert row['start_ply'] >= 1
    assert events
    for row in events:
        assert row['available_after_ply'] >= row['event_ply']


def test_features_have_no_label_columns_and_are_deterministic(corpus):
    data, add = corpus
    for i in range(1,4):
        add(i)
    compute(data, min_prior_games=1)
    before = {p.name: p.read_bytes() for p in (data/'processed' / 'features').glob('*.parquet')}
    compute(data, min_prior_games=1)
    assert before == {p.name:p.read_bytes() for p in (data/'processed' / 'features').glob('*.parquet')}
    for path in (data/'processed' / 'features').glob('*.parquet'):
        cols = pd.read_parquet(path).columns
        assert not any('label' in c or 'tilt' in c or 'questionnaire' in c for c in cols)
    assert json.loads((data/'processed/features/manifest.json').read_text())['min_prior_games'] == 1


def test_mating_move_is_not_a_missed_mate_or_error(api_raw):
    raw=deepcopy(api_raw)
    raw['analysis'][-2]={'mate':1}
    game,moves=api_game(raw)
    rows,_=move_features(game,moves,{})
    assert rows[-1]['judgement']=='good'
    assert not rows[-1]['just_missed_mate']


def test_opponent_event_window_includes_first_response(api_raw):
    game,moves=api_game(api_raw)
    rows,_=move_features(game,moves,{})
    own=[r for r in rows if r['player']=='alice']
    own[1]['opponent_just_took_advantage']=True
    own[1]['adverse_event']=True
    _,events=windows_and_events(own,2)
    event=next(r for r in events if 'opponent_just_took_advantage' in r['event_types'])
    assert event['event_ply']==own[1]['ply']-1
    assert event['post_count']==1
    assert event['post_mean_cpl']==own[1]['cpl']


def test_feature_dictionary_covers_all_emitted_columns(corpus):
    from pathlib import Path
    data,add=corpus
    add(1)
    compute(data,min_prior_games=1)
    dictionary=(Path(__file__).parents[2]/'docs'/'phu-luc-cot-dac-trung.md').read_text()
    for path in (data/'processed' / 'features').glob('*.parquet'):
        for col in pd.read_parquet(path).columns:
            assert f'`{col}`' in dictionary, (path.name,col)


def test_zero_increment_stays_known_with_missing_berserk_metadata(api_raw):
    raw=deepcopy(api_raw)
    raw['clock']['increment']=0
    raw['clocks']=[clock//2 for clock in raw['clocks']]
    game,moves=api_game(raw)
    rows,_=move_features(game,moves,{})
    assert rows[2]['clock_config_mismatch']
    assert rows[2]['think_seconds']==1
    raw['clock']['increment']=2
    game,moves=api_game(raw)
    rows,_=move_features(game,moves,{})
    assert rows[2]['think_seconds'] is None


def reference_robust(current, history, columns, minimum):
    """Small independent pre-optimisation algorithm, deliberately scans history."""
    import statistics
    from tilt.features.features import mean, valid
    out, scores = {}, []
    for name, floor in columns.items():
        vals = [h[name] for h in history if valid(h.get(name))]
        count = len({h['game_id'] for h in history if valid(h.get(name))})
        median = statistics.median(vals) if count >= minimum else None
        mad = statistics.median([abs(v - median) for v in vals]) if median is not None else None
        z = (current[name] - median) / max(1.4826 * mad, floor) if median is not None and valid(current.get(name)) else None
        out[f'baseline_{name}_games'] = count
        out[f'baseline_{name}_median'] = median
        out[f'baseline_{name}_mad'] = mad
        out[f'deviation_{name}_z'] = z
        out[f'historical_{name}_similar_fraction'] = mean([abs(v - current[name]) <= max(1.4826 * mad, floor) for v in vals]) if z is not None else None
        if z is not None:
            scores.append(min(10, abs(z)))
    out['behavioral_deviation_score'] = mean(scores) * 10 if scores else None
    out['deviation_feature_count'] = len(scores)
    return out


def test_bounded_baselines_match_small_reference(corpus):
    from tilt.features.features import MOVE_BASELINES, GAME_BASELINES
    data, add = corpus
    add(1, start=100000, end=450000, error=True)
    add(2, start=200000, end=260000)
    add(3, start=300000, end=360000, error=True)
    add(4, start=500000, end=560000)
    compute(data, min_prior_games=1, max_history_games=10)
    games = storage.records(pd.read_parquet(data / 'processed/features/games.parquet'))
    moves = storage.records(pd.read_parquet(data / 'processed/features/moves.parquet'))
    for current in games + moves:
        is_move = 'ply' in current
        source = moves if is_move else games
        history = [r for r in source if r['player'] == current['player'] and r['speed'] == current['speed']
                   and r['end_upper_ms'] < current['start_ms'] and (not is_move or
                   (r['clock_pressure'], r['advantage_state']) == (current['clock_pressure'], current['advantage_state']))]
        expected = reference_robust(current, history, MOVE_BASELINES if is_move else GAME_BASELINES, 1)
        assert {k: current[k] for k in expected} == expected


def test_cap_keeps_latest_by_end_not_start_or_oldest_and_normal_cpl(corpus, monkeypatch):
    import statistics
    import tilt.features.features as features
    data, add = corpus
    add(1, start=100000, end=450000, error=True)  # oldest start, most recent end
    add(2, start=200000, end=260000)
    add(3, start=300000, end=360000, error=True)
    add(4, start=500000, end=560000)
    captured = {}
    original = features.windows_and_events
    def capture(rows, window, normal_cpl=None):
        captured[rows[0]['game_id'], rows[0]['player']] = normal_cpl
        return original(rows, window, normal_cpl)
    monkeypatch.setattr(features, 'windows_and_events', capture)
    compute(data, min_prior_games=1, max_history_games=2)
    games = pd.read_parquet(data / 'processed/features/games.parquet')
    moves = pd.read_parquet(data / 'processed/features/moves.parquet')
    current = storage.records(games[(games.player == 'alice') & (games.game_id == 'game0004')])[0]
    recent = storage.records(games[(games.player == 'alice') & games.game_id.isin(['game0001', 'game0003'])])
    assert current['history_games'] == 3
    assert current['baseline_speed_games'] == 2
    assert current['baseline_mean_cpl_games'] == 2
    assert current['baseline_mean_cpl_median'] == statistics.median(g['mean_cpl'] for g in recent)
    assert current['baseline_latest_end_ms'] == max(g['end_upper_ms'] for g in recent)
    vals = moves[(moves.player == 'alice') & moves.game_id.isin(['game0001', 'game0003'])].cpl.dropna().tolist()
    med = statistics.median(vals)
    assert captured['game0004', 'alice'] == med + max(1, 1.4826 * statistics.median(abs(v - med) for v in vals))
    assert json.loads((data / 'processed/features/manifest.json').read_text())['max_history_games'] == 2
    with pytest.raises(ValueError, match='maximum history'):
        compute(data, max_history_games=0)


def test_sorted_similarity_matches_original_float_boundary_comparison():
    # Repeated boundary values must be handled with bisect, not row-wise scans.
    history = [{'game_id': str(i), 'x': x} for i, x in enumerate([1.2, 1.3, 1.4, 1.5] * 20)]
    for current in (1.2, 1.3, 1.4, 1.5, 1.35, float('nan'), None):
        row = {'x': current}
        assert robust(row, history, {'x': .1}, 1) == reference_robust(row, history, {'x': .1}, 1)
    history = [{'game_id': str(i), 'x': x} for i, x in enumerate([1e16] * 200 + [1e16 + 2] * 200)]
    row = {'x': 1e16}
    assert robust(row, history, {'x': 1}, 1) == reference_robust(row, history, {'x': 1}, 1)


def test_history_cap_is_per_speed_before_context_filtering(corpus, api_raw):
    data, add = corpus
    add(1)
    raw = deepcopy(api_raw)
    raw.update(id='rapid001', speed='rapid', createdAt=200000, lastMoveAt=260000)
    game, moves = api_game(raw)
    storage.append(data, [game], moves)
    add(3)
    add(4)
    compute(data, min_prior_games=1, max_history_games=2)
    games = pd.read_parquet(data / 'processed/features/games.parquet')
    row = games[(games.player == 'alice') & (games.game_id == 'game0004')].iloc[0]
    assert row.history_games == 3 and row.baseline_speed_games == 2
    expected = games[(games.player == 'alice') & games.game_id.isin(['game0001', 'game0003'])].mean_cpl.median()
    assert row.baseline_mean_cpl_median == expected
    assert row.baseline_mean_cpl_games == 2
