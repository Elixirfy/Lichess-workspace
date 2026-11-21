"""Small, offline fixtures for weak labels, features, sequence, train, evaluate, score."""
import ast
import inspect
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from tilt.data import storage
from tilt.data.dataset import _safe_export
from tilt.labels.labels import pseudonym, private_id
from tilt.labels.weak_labels import (ABSTAIN, LFS, LabelModel, attach_labels, build,
                              contexts, load_cohort, split_rows, vote, outcome_gate, _split_player)
from tilt.features.model_features import assert_no_lf_inputs, feature_list, prepare, audit_outcome_proxies, audit_lf_proxies, passes_audits
from tilt.training.sequence import fit, materialize, predict, prior_indices
from tilt.training.train import aligned, calibrate, calibrated, choose_threshold, run as train, predict_bundle
from tilt.evaluation.evaluate import metrics, bootstrap, reliability, outcome_metrics, beats_baselines, run as evaluate
from tilt.service.score import band, prefix_snapshot, run as score


@pytest.fixture
def weak_corpus(tmp_path):
    games, features, moves = [], [], []
    users = [f'synthetic_player_{p:02}' for p in range(24)]
    for p, player in enumerate(users):
        for i in range(12):
            gid = f'synthetic_game_{p:02}_{i:02}'
            start = 1_000_000 + (40000 if i == 1 else i * 1_000_000) + p * 1000
            loss = i % 4 == 0
            games.append(dict(game_id=gid, white=player, black='synthetic_opponent',
                              white_rating=1200, black_rating=1250, speed='blitz', initial_seconds=180,
                              increment_seconds=2, start_ms=start, end_ms=start + 10000,
                              end_upper_ms=start + 10001, status=('outoftime' if i == 4 else 'timeout') if loss else 'mate', plies=80))
            features.append(dict(player=player, opponent='synthetic_opponent', game_id=gid,
                                 session_id=f'session_{p}_{0 if i == 1 else i}', start_ms=start, end_ms=start + 10000,
                                 end_upper_ms=start + 10001, speed='blitz', rating=1200 + p * 20,
                                 opponent_rating=1250, rating_difference=-50, result_score=0 if loss else 1,
                                 losing_streak_before=0 if loss else 1, rest_gap_seconds=990,
                                 games_in_session_before=0, history_games=i, baseline_speed_games=i,
                                 baseline_latest_end_ms=start - 989999 if i else None,
                                 mean_accuracy=60 if loss or i == 1 else 90, baseline_mean_accuracy_median=80,
                                 mean_cpl=150 if loss else 20, deviation_mean_cpl_z=2 if loss or i == 1 else 0,
                                 adverse_events=1 if loss else 0, mean_think=4 if loss else 12,
                                 think_std=2, risk_rate=.5 if loss else .1, attack_rate=.3,
                                 baseline_mean_think_median=10 if i else None, baseline_mean_think_mad=1 if i else None,
                                 deviation_mean_think_z=-4 if loss and i else 1 if i else None,
                                 historical_mean_think_similar_fraction=.5 if i else None,
                                 behavioral_deviation_score=50 if loss else 10))
            for ply in (1, 3, 5):
                moves.append(dict(player=player, game_id=gid, ply=ply, eval_after_cp=-200 if loss else 200,
                                  eval_after_mate=None, adverse_event=loss and ply == 5,
                                  clock_fraction=1 - ply * .03, phase='opening' if ply <= 3 else 'middlegame',
                                  cpl=120 if loss else 20, accuracy=60 if loss else 90, wc_loss=.05,
                                  think_seconds=float(ply + 1), judgement='mistake' if loss else 'good',
                                  risk=int(loss), attack=1, defensive=0, sacrifice_heuristic=0,
                                  unsound_attack=0, unsound_sacrifice_realized=0, style_switch=0,
                                  consecutive_errors=1 if loss else 0, advantage_state='equal', think_per_legal_move=.2))
    storage.append(tmp_path, games, [])
    storage.write_frame(tmp_path / 'processed/features/games.parquet', pd.DataFrame(features))
    storage.write_frame(tmp_path / 'processed/features/moves.parquet', pd.DataFrame(moves))
    (tmp_path / 'processed/features/manifest.json').write_text(json.dumps(dict(max_history_games=200, min_prior_games=1)))
    users_file = tmp_path / 'users.txt'
    users_file.write_text('\n'.join(users))
    return tmp_path, users_file


def test_lf_votes_thresholds_and_missingness():
    assert vote({}) == [ABSTAIN] * len(LFS)
    assert vote(dict(status='timeout', result_score=0))[0] == ABSTAIN
    assert vote(dict(status='timeout', result_score=0, final_eval_cp=0, final_eval_mate=None, last_adverse_distance=2))[0] == 1
    assert vote(dict(status='outoftime', result_score=0))[0] == ABSTAIN
    row = dict(status='resign', result_score=0, plies=40, final_eval_cp=-100, final_eval_mate=None, last_adverse_distance=4)
    assert vote(row)[1] == 1
    row['final_eval_cp'] = -151
    assert vote(row)[1] == ABSTAIN
    assert vote(dict(result_score=1, start_ms=60000, previous_end_upper_ms=1000,
                     previous_result_score=0, previous_same_session=True, deviation_mean_cpl_z=2))[2] == 1
    assert vote(dict(result_score=1, prior_session_loss_run=3, session_shrinking_gaps=True, deviation_mean_cpl_z=2))[3] == 1
    assert vote(dict(status='mate', plies=80, result_score=0, mean_accuracy=90, baseline_mean_accuracy_median=85, deviation_mean_cpl_z=.5))[4] == 0
    assert vote(dict(status='mate', plies=80, next_start_ms=601000, end_upper_ms=1000, next_deviation_mean_cpl_z=.5))[5] == 0
    assert vote(dict(status='draw', plies=80, result_score=.5, adverse_events=0, mean_accuracy=90, baseline_mean_accuracy_median=85))[6] == 0


def test_lf_declarations_cover_direct_reads():
    tree = ast.parse(inspect.getsource(vote))
    reads = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == 'row' and isinstance(node.slice, ast.Constant):
            reads.add(node.slice.value)
        if isinstance(node, ast.Call) and ((isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == 'row') or (isinstance(node.func, ast.Name) and node.func.id == 'known')):
            reads.update(a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str))
    assert reads <= {c for lf in LFS for c in lf.inputs}


def test_label_model_no_vote_conflict_and_no_test_fit():
    votes = np.array([[1, 1, -1], [0, 0, -1], [1, -1, 1], [0, -1, 0]] * 5)
    model = LabelModel().fit(votes)
    before = model.state()
    p = model.predict(np.array([[1, 1, -1], [0, 0, -1], [-1, -1, -1], [1, 0, -1]]))
    assert p[0] > .5 > p[1] and np.isnan(p[2]) and np.isfinite(p[3])
    model.predict(np.ones((100, 3), dtype=int))
    assert model.state() == before
    table = attach_labels(pd.DataFrame(index=range(1)), np.full((1, len(LFS)), -1), LabelModel().fit(np.tile([1, 1, 0, 0] + [-1] * (len(LFS)-4), (5, 1))))
    assert pd.isna(table.weak_tilt_label.iloc[0])
    empty_model = LabelModel().fit(np.full((3, len(LFS)), ABSTAIN))
    assert np.isnan(empty_model.predict(np.full((2, len(LFS)), ABSTAIN))).all()
    assert empty_model.state()['fitted_rows'] == 0


def test_all_lf_columns_and_same_raw_quantity_excluded(weak_corpus):
    data, users = weak_corpus
    build(data, users)
    frame = aligned(data)
    inputs = {c for lf in LFS for c in lf.inputs}
    for variant in ('full', 'no_history', 'lf_ablated', 'lf_ablated_no_history'):
        columns = feature_list(frame, variant)
        assert not set(columns) & inputs
        assert not any('accuracy' in c or 'cpl' in c or c.endswith('_ms') for c in columns)
        assert 'behavioral_deviation_score' not in columns
        assert_no_lf_inputs(columns, variant.startswith('lf_ablated'))
    for col in inputs | {'baseline_mean_cpl_median', 'deviation_mean_accuracy_z', 'behavioral_deviation_score', 'baseline_latest_end_ms', 'tense_think_std', 'sacrifice_rate'}:
        with pytest.raises(ValueError, match='LF provenance'):
            assert_no_lf_inputs([col])


def test_exports_private_no_human_store_and_disjoint_split(weak_corpus):
    data, users = weak_corpus
    result = build(data, users)
    assert result['players'] == 24 and result['rows'] == 288
    assert not (data / 'raw' / 'labels').exists()
    for path in (data / 'processed' / 'out').glob('*.parquet'):
        frame = pd.read_parquet(path)
        text = frame.to_json()
        assert 'synthetic_player_' not in text and 'synthetic_game_' not in text and 'synthetic_opponent' not in text
    frame = pd.read_parquet(data / 'processed/out/weak_by_player.parquet')
    assert {'lf_input__plies', 'lf_input__status', 'lf_input__next_rest_gap_seconds',
            'lf_input__last_adverse_distance', 'lf_input__ply__max'} <= set(frame)
    assert frame.weak_tilt_label.nunique() == 2
    assert (frame.groupby('player_id').split.nunique() == 1).all()
    for path in (data / 'processed' / 'out').glob('*.json'):
        assert 'synthetic_player_' not in path.read_text()
    assert load_cohort(data, users).player.nunique() == 24


def test_future_label_horizon_and_shared_dependencies_are_purged():
    names = {p: next(f'fixture{i}' for i in range(1000) if _split_player(pseudonym(f'fixture{i}')) == p) for p in ('train', 'test')}
    frame = pd.DataFrame(dict(player_id=[pseudonym(names['train']), pseudonym(names['test'])],
                              start_ms=[0, 10], end_upper_ms=[1, 11], label_end_upper_ms=[20, 11]))
    splits, _ = split_rows(frame, [{'game-a', 'future-shared-game'}, {'future-shared-game'}])
    assert splits['by_player'][0] == 'purged_shared_game'
    assert splits['by_time'][0] == 'purged_crossing_cutoff'


def test_build_label_model_never_fits_held_out_votes(weak_corpus):
    data, users = weak_corpus
    first = build(data, users)['splits']['by_player']['model']
    path = data / 'processed/features/games.parquet'
    frame = pd.read_parquet(path)
    held = frame.player.map(lambda p: _split_player(pseudonym(p))) != 'train'
    frame.loc[held, 'result_score'] = 0
    frame.loc[held, 'adverse_events'] = 8
    frame.loc[held, 'mean_accuracy'] = 10
    storage.write_frame(path, frame)
    second = build(data, users)['splits']['by_player']['model']
    assert first == second


def test_terminal_eval_includes_opponent_final_move(weak_corpus):
    data, users = weak_corpus
    frame = load_cohort(data, users)
    moves_path = data / 'processed/features/moves.parquet'
    moves = pd.read_parquet(moves_path)
    other = dict(moves.iloc[0])
    other.update(player='synthetic_opponent', ply=6, eval_after_cp=-100, adverse_event=False)
    storage.write_frame(moves_path, pd.concat([moves, pd.DataFrame([other])], ignore_index=True))
    ctx, _ = contexts(data, frame)
    assert ctx.final_eval_cp.iloc[0] == 100


def test_sequence_strict_prior_deterministic_cpu():
    frame = pd.DataFrame(dict(player_id=['a'] * 4, game_id=list('abcd'),
                              start_ms=[0, 10, 15, 30], end_upper_ms=[5, 20, 16, 40]))
    indices = prior_indices(frame, 3)
    assert indices[2].tolist() == [-1, 0, 2]  # b overlaps c
    x = materialize(np.arange(8, dtype=np.float32).reshape(4, 2), indices)
    a = fit(x, np.array([0, 1, 0, 1]), np.array([.1, .9, .2, .8]), np.array([0, 1, 2]), np.array([3]), epochs=1, threads=1)
    b = fit(x, np.array([0, 1, 0, 1]), np.array([.1, .9, .2, .8]), np.array([0, 1, 2]), np.array([3]), epochs=1, threads=1)
    assert np.allclose(predict(a, x)[0], predict(b, x)[0])
    assert np.all((predict(a, x)[0] >= 0) & (predict(a, x)[0] <= 1))


def test_metrics_calibration_bootstrap_edges():
    f = pd.DataFrame(dict(player_id=['a', 'a', 'b', 'b'], weak_tilt_label=[0, 1, 0, 1],
                          weak_tilt_prob=[0, 1, 0, 1], predicted_weak_tilt_prob=[.1, .9, .2, .8],
                          predicted_weak_tilt_score_regression=[0, 100, 0, 100]))
    m = metrics(f, .5)
    assert m['f1'] == m['roc_auc'] == m['pr_auc'] == 1
    assert m['mae'] == m['rmse'] == 0
    assert bootstrap(f, .5, 5)['clusters'] == 2
    assert sum(r['n'] for r in reliability(f)) == 4
    assert metrics(f.iloc[:1], .5)['roc_auc'] is None
    assert calibrate(np.array([.1, .9]), np.array([0, 1]))['model'] is None
    p = np.tile([.1, .9], 20)
    c = calibrate(p, np.tile([0, 1], 20))
    assert c['model'] is not None and calibrated(c, p)[1] > calibrated(c, p)[0]
    assert [band(x) for x in (0, 25, 26, 50, 51, 75, 76, 100)] == ['0–25', '0–25', '26–50', '26–50', '51–75', '51–75', '76–100', '76–100']


def test_threshold_validation_only_and_higher_tie_break():
    # Both .2 and .3 give F1 = 2/3; the higher threshold must win.
    frame = pd.DataFrame(dict(
        split=['train'] * 100 + ['validation'] * 24 + ['test'] * 20,
        y=[0] * 90 + [1] * 10 + [1] * 12 + [0] * 12 + [0, 1] * 10,
        p=list(np.linspace(0, 1, 100)) + [.3] * 6 + [.2] * 18 + [.99, .01] * 10))

    def select(f):
        train, val = f[f.split.eq('train')], f[f.split.eq('validation')]
        return choose_threshold(train.p, train.y, val.p, val.y)

    original = select(frame)
    assert original['threshold'] == .3
    assert original['threshold_source'].startswith('validation F1')
    frame.loc[frame.split.eq('test'), ['p', 'y']] = [1, 1]
    assert select(frame) == original
    # Validation actually controls the threshold when sufficiently populated.
    frame.loc[frame.split.eq('validation'), 'p'] += .1
    assert select(frame)['threshold'] == pytest.approx(.4)


@pytest.mark.parametrize('validation_y', [[1] * 9 + [0] * 31, [0] * 40, [1] * 12])
def test_threshold_train_quantile_fallback(validation_y):
    p = np.linspace(.01, .99, 100)
    y = np.array([0] * 90 + [1] * 10)
    chosen = choose_threshold(p, y, np.linspace(0, 1, len(validation_y)), validation_y)
    assert chosen['threshold_source'].startswith('train calibrated-score quantile')
    assert np.mean(p >= chosen['threshold']) == pytest.approx(y.mean())
    assert chosen == choose_threshold(p, y, np.zeros(len(validation_y)), validation_y)
    if len(set(validation_y)) == 2:
        calibration = calibrate(np.linspace(.01, .99, len(validation_y)), np.array(validation_y))
        assert calibration['model'] is None
        assert 'fewer than 10 validation weak positives' in calibration['status']


def test_threshold_tied_train_scores_are_explicit():
    chosen = choose_threshold(np.full(100, .1), np.array([0] * 90 + [1] * 10), [], [])
    assert chosen['threshold'] == .1
    assert 'score ties may prevent exact rate' in chosen['threshold_source']


@pytest.mark.parametrize('positives', [9, 10])
def test_calibration_validation_positive_boundary(positives):
    y = np.r_[np.zeros(30), np.ones(positives)]
    p = np.where(y, .8, .2)
    calibration = calibrate(p, y)
    if positives < 10:
        assert calibration['model'] is None
        np.testing.assert_array_equal(calibrated(calibration, p), p)
        assert 'fewer than 10 validation weak positives' in calibration['status']
    else:
        assert calibration['model'] is not None


def test_metrics_strata_and_bootstrap_use_threshold():
    f = pd.DataFrame(dict(player_id=['a', 'a', 'b', 'b'], result_score=[0, 0, 1, 1],
                          weak_tilt_label=[0, 1, 0, 1], weak_tilt_prob=[0, 1, 0, 1],
                          predicted_weak_tilt_prob=[.1, .4, .2, .3],
                          predicted_weak_tilt_score_regression=[0, 100, 0, 100]))
    stored = dict(threshold=.25)
    assert metrics(f, stored['threshold'])['f1'] == 1
    assert metrics(f, .5)['f1'] == 0
    assert all(m['f1'] == 1 for m in outcome_metrics(f, stored['threshold']).values())
    assert bootstrap(f, stored['threshold'], 5)['f1'] == [1, 1]


def test_weak_player_split_60_20_20_and_stable(monkeypatch):
    from tilt.data.dataset import _split_player as human_split
    ids = [f'synthetic-id-{i}' for i in range(600)]
    first = [_split_player(pid) for pid in ids]
    proportions = pd.Series(first).value_counts(normalize=True)
    for part, expected in [('train', .6), ('validation', .2), ('test', .2)]:
        assert proportions[part] == pytest.approx(expected, abs=.04)
    monkeypatch.setenv('TILT_SALT', 'different-synthetic-test-salt')
    assert [_split_player(pid) for pid in ids] == first
    assert [p == 'test' for p in first] == [human_split(pid) == 'test' for pid in ids]


def test_weak_time_split_70_85_unique_start_cutoffs():
    starts = np.repeat(np.arange(200) * 1000, 2)
    frame = pd.DataFrame(dict(player_id=[f'id-{i}' for i in range(len(starts))],
                              start_ms=starts, end_upper_ms=starts + 1, label_end_upper_ms=starts + 1))
    splits, cutoffs = split_rows(frame, [{f'game-{i}'} for i in range(len(frame))])
    assert cutoffs == dict(validation_ms=140000, test_ms=170000)
    assert pd.Series(splits['by_time']).value_counts().to_dict() == dict(train=280, validation=60, test=60)


def test_prefix_snapshot_invariant_to_future(weak_corpus):
    data, _ = weak_corpus
    games = pd.read_parquet(data / 'processed/features/games.parquet')
    g = storage.records(games.iloc[:1])[0]
    moves = pd.read_parquet(data / 'processed/features/moves.parquet')
    own = moves[(moves.game_id == g['game_id']) & (moves.ply <= 3)]
    config = dict(max_history_games=200, min_prior_games=1)
    before = prefix_snapshot(g, own, games.iloc[:0], config)
    changed = {**g, 'mean_think': 9999, 'risk_rate': .99, 'style_drift_in_session': 1, 'behavioral_deviation_score': 100}
    after = prefix_snapshot(changed, own, games.iloc[:0], config)
    pd.testing.assert_frame_equal(before, after)
    assert before.mean_think.iloc[0] == own.think_seconds.mean()


def test_small_end_to_end_all_models_and_score(weak_corpus):
    data, users = weak_corpus
    build(data, users)
    result = train(data, epochs=1, trees=4, threads=1, variants=('full', 'no_history', 'lf_ablated', 'lf_ablated_no_history'))
    assert result['trained'] == 38  # 4 models × 4 variants × 2 splits + 6 diagnostics
    evaluate(data, bootstrap_repetitions=3)
    report = (data / 'processed/out/MODEL_REPORT.md').read_text()
    assert 'not measured emotions' in report and 'How to validate with human labels' in report
    selected = json.loads((data / 'processed/models/selection.json').read_text())['selected']['by_player']
    bundle = joblib.load(data / 'processed' / 'models' / f'{selected}.joblib')
    assert_no_lf_inputs(bundle['features'])
    assert 'clock_fraction_last' not in bundle['features']
    summary = json.loads((data / 'processed/out/weak_metrics.json').read_text())
    gates = summary['outcome_gates']
    assert ('FAILED: label ≈ outcome' in report) == any(g['failed'] for g in gates.values())
    assert 'Train-only outcome-proxy audit' in report
    assert 'Train-only LF-provenance proxy audit' in report
    assert 'Features removed by outcome audit (every variant)' in report
    assert 'Features removed by LF-provenance audit (every variant)' in report
    assert 'losses only' in report and 'non_losses only' in report
    assert 'beats both trivial' not in report
    for split in ('by_player', 'by_time'):
        diagnostic = summary['results'][f'{split}__baseline__result_only']
        assert diagnostic['model'] == 'result_only'
        assert summary['selection']['selected'].get(split) != diagnostic['id']
    for result in summary['results'].values():
        prediction = pd.read_parquet(data / 'processed' / 'out' / f"predictions__{result['id']}.parquet")
        parts = [prediction[prediction.split.eq(part) & prediction.weak_tilt_label.notna()]
                 for part in ('train', 'validation')]
        expected = choose_threshold(parts[0].predicted_weak_tilt_prob.to_numpy(dtype=float),
                                    parts[0].weak_tilt_label.to_numpy(dtype=float),
                                    parts[1].predicted_weak_tilt_prob.to_numpy(dtype=float),
                                    parts[1].weak_tilt_label.to_numpy(dtype=float))
        assert result['threshold'] == expected['threshold']
        assert result['threshold_source'] == expected['threshold_source']
        saved_bundle = joblib.load(data / 'processed' / 'models' / f"{result['id']}.joblib")
        assert saved_bundle['threshold'] == result['threshold']
        assert saved_bundle['threshold_source'] == result['threshold_source']
        test = prediction[prediction.split.eq('test')]
        assert result['test'] == metrics(test, result['threshold'])
        assert result['outcome_strata']['test'] == outcome_metrics(test, result['threshold'])
        for speed, group in test.groupby('speed'):
            values = result['breakdowns']['speed'][speed]
            assert {k: v for k, v in values.items() if k != 'ci'} == metrics(group, result['threshold'])
        if result['variant'] != 'baseline':
            assert passes_audits(result['features'], summary['outcome_proxy_audits'][result['split']],
                                 summary['lf_proxy_audits'][result['split']])
        assert set(result['outcome_strata']['test']) == {'losses', 'non_losses'}
    for path in (data / 'processed' / 'out').glob('predictions__*.parquet'):
        prediction = pd.read_parquet(path)
        assert {'result_score', 'status'} <= set(prediction)
        if 'result_only' in path.name:
            np.testing.assert_array_equal(prediction.predicted_weak_tilt_prob, prediction.result_score.eq(0).astype(float))
    output = score(data, 'synthetic_player_00', 'synthetic_game_00_00')
    assert len(output['games']) == 1 and output['games'][0]['timeline']
    assert 0 <= output['games'][0]['weak_model_tilt_score'] <= 100
    assert output['threshold'] == bundle['threshold']
    assert output['threshold_source'] == bundle['threshold_source']
    # Make the saved threshold deliberately decisive, preserving scores.
    bundle['threshold'] = 0
    joblib.dump(bundle, data / 'processed' / 'models' / f'{selected}.joblib')
    flagged = score(data, 'synthetic_player_00', 'synthetic_game_00_00')
    assert flagged['games'][0]['weak_model_tilt_score'] == output['games'][0]['weak_model_tilt_score']
    assert flagged['games'][0]['weak_model_tilt_flag']
    assert all(point['weak_model_tilt_flag'] for point in flagged['games'][0]['timeline'])
    assert '60/20/20' in report and '70/85' in report and 'Threshold = 0.5' not in report
    assert '| Partition | Players | Rows | Labelled rows | Weak positives | Positive rate |' in report
    assert 'Threshold source' in report
    for split, diagnostics in summary['selection']['diagnostics'].items():
        selected_result = summary['results'][summary['selection']['selected'][split]]
        assert diagnostics['validation_positives'] == selected_result['validation_positives']
        assert bool(diagnostics['warning']) == (diagnostics['validation_positives'] < 30)
        if diagnostics['warning']:
            assert '**Warning: Fewer than 30 validation weak positives' in report
    for path in (data / 'processed' / 'out').glob('*'):
        if path.suffix in ('.md', '.json'):
            assert 'synthetic_player_' not in path.read_text()
        elif path.suffix == '.parquet':
            assert 'synthetic_player_' not in pd.read_parquet(path).to_json()
    # Even a previously winning full variant becomes ineligible if its recorded
    # inputs fail either audit; evaluate must not trust its name or old score.
    manifest_path = data / 'processed/models/manifest.json'
    manifest = json.loads(manifest_path.read_text())
    winner = next(r for r in manifest['runs'] if r['id'] == selected)
    winner['features'] = ['risk_rate']  # Strong LF-quality proxy in this fixture.
    manifest_path.write_text(json.dumps(manifest))
    evaluate(data, bootstrap_repetitions=2)
    selection = json.loads((data / 'processed/models/selection.json').read_text())
    assert selection['selected'].get('by_player') != selected


@pytest.mark.parametrize('positive_fraction', [.05, .5, .95])
def test_label_model_direction_and_neutral_abstention(positive_fraction):
    n = 100
    # Outcome-dependent one-sided coverage must not become class evidence.
    votes = np.full((n, 4), ABSTAIN)
    cut = int(n * positive_fraction)
    votes[:cut, :2] = 1
    votes[cut:, 2:] = 0
    model = LabelModel().fit(votes)
    probes = np.array([[0, -1, -1, -1], [-1, 0, -1, -1], [-1, -1, 0, 0],
                       [1, -1, -1, -1], [-1, -1, 1, 1]])
    p = model.predict(probes)
    assert np.all(p[:3] < model.prior) and np.all(p[:3] < .5)
    assert np.all(p[3:] > model.prior)
    assert np.all(model.accuracies >= .5)
    # Padding with a never-voting LF cannot change fitting or prediction.
    padded = LabelModel().fit(np.c_[votes, np.full((n, 3), ABSTAIN)])
    np.testing.assert_allclose(p, padded.predict(np.c_[probes, np.full((len(probes), 3), ABSTAIN)]), atol=1e-12)
    # The likelihood of an abstention is identically neutral for every LF.
    signed = np.where(probes == ABSTAIN, 0, 2 * probes - 1)
    odds = np.log(model.prior / (1-model.prior)) + signed @ np.log(model.accuracies / (1-model.accuracies))
    np.testing.assert_allclose(p, 1/(1+np.exp(-odds)))
    # Extra NOT_TILT evidence can never raise probability, even in conflicts.
    assert model.predict([[1, -1, -1, -1]])[0] >= model.predict([[1, 0, -1, -1]])[0]


def test_lfs_both_classes_in_each_outcome_and_current_carryover():
    by_name = lambda row: dict(zip((lf.name for lf in LFS), vote(row)))
    tilted = dict(previous_result_score=0, previous_end_upper_ms=1000, previous_same_session=True,
                  start_ms=31000, deviation_mean_cpl_z=2, mean_think=5, baseline_mean_think_median=10)
    composed = dict(status='resign', plies=100, final_eval_cp=-600, final_eval_mate=None,
                    end_upper_ms=1000, next_start_ms=601000, next_deviation_mean_cpl_z=.5)
    for result in (0, .5, 1):
        votes = by_name(dict(tilted, result_score=result))
        assert votes['carryover'] == votes['fast_erratic_after_loss'] == 1
        calm = by_name(dict(status='mate', plies=80, result_score=result, mean_accuracy=85, baseline_mean_accuracy_median=80,
                            deviation_mean_cpl_z=.5, adverse_events=0))
        assert calm['normal_accuracy'] == calm['calm_play'] == 0
    assert by_name(dict(composed, result_score=0))['composed_loss'] == 0
    assert by_name(dict(status='mate', plies=80, result_score=0, rating_difference=-250, mean_accuracy=76,
                        baseline_mean_accuracy_median=80, deviation_mean_cpl_z=.5))['expected_loss'] == 0
    assert by_name(dict(tilted, result_score=0, previous_result_score=1))['carryover'] == ABSTAIN
    assert by_name(dict(tilted, previous_same_session=False))['carryover'] == ABSTAIN
    assert by_name(dict(result_score=0, end_upper_ms=1000, next_start_ms=31000,
                        next_deviation_mean_cpl_z=2))['carryover'] == ABSTAIN
    assert by_name(dict(tilted, previous_end_upper_ms=32000))['carryover'] == ABSTAIN
    assert by_name(dict(composed, result_score=0, plies=60))['composed_loss'] == ABSTAIN


def test_current_carryover_context_and_horizon(weak_corpus):
    data, users = weak_corpus
    path = data / 'processed/features/games.parquet'
    frame = pd.read_parquet(path)
    # First game is a loss. The second completes after a quick same-session start.
    frame.loc[1, ['start_ms', 'end_upper_ms', 'session_id', 'deviation_mean_cpl_z']] = [
        frame.loc[0, 'end_upper_ms'] + 30000, frame.loc[0, 'end_upper_ms'] + 40000, frame.loc[0, 'session_id'], 2]
    storage.write_frame(path, frame)
    ordered = load_cohort(data, users)
    ctx, deps = contexts(data, ordered)
    assert vote(storage.records(ctx.iloc[1:2])[0])[2] == 1
    assert vote(storage.records(ctx.iloc[:1])[0])[2] == ABSTAIN
    assert ordered.game_id.iloc[0] in deps[1]
    # Unrelated future session games must not extend current evidence scope.
    before = ctx.iloc[1].previous_result_score
    frame.loc[2:, 'result_score'] = 0
    storage.write_frame(path, frame)
    after, _ = contexts(data, load_cohort(data, users))
    assert after.iloc[1].previous_result_score == before
    assert pd.isna(ctx.iloc[1].get('next_deviation_mean_cpl_z'))


def test_outcome_gate_train_only_boundaries_and_empty_strata():
    rows = []
    for loss in (True, False):
        for i in range(20):
            rows.append(dict(result_score=0 if loss else 1, weak_tilt_label=int(i < 10), split='train'))
    frame = pd.DataFrame(rows)
    assert outcome_gate(frame)['status'] == 'PASSED'
    assert outcome_gate(frame)['agreement'] == .5
    frame.weak_tilt_label = frame.result_score.eq(0).astype(int)
    gate = outcome_gate(frame)
    assert gate['failed'] and gate['status'] == 'FAILED: label ≈ outcome'
    assert outcome_gate(frame.iloc[:0])['failed']
    assert outcome_gate(frame.iloc[:20])['failed']
    # Exactly .75 agreement and 10% minority are allowed; above/below fail.
    boundary = pd.DataFrame(dict(result_score=[0]*20 + [1]*20,
                                 weak_tilt_label=[1]*18+[0]*2 + [1]*8+[0]*12))
    assert outcome_gate(boundary)['agreement'] == .75
    assert not outcome_gate(boundary)['failed']
    boundary.loc[27, 'weak_tilt_label'] = 0
    assert outcome_gate(boundary)['failed']


def test_outcome_proxy_audit_uses_train_and_removes_both_directions():
    train = pd.DataFrame(dict(split=['train']*40, result_score=[0, 1]*20,
                              status=['outoftime', 'mate', 'mate', 'outoftime']*10,
                              risk_rate=[0, 1]*20, attack_rate=[1, 0, 0, 1]*10,
                              defensive_rate=[0, 0, 1, 1]*10, style_switch_rate=[2]*40,
                              clock_fraction_last=[0, 1]*20))
    held = train.copy()
    held['split'] = 'test'
    frame = pd.concat([train, held], ignore_index=True)
    audit = audit_outcome_proxies(frame)
    records = {r['feature']: r for r in audit}
    assert records['risk_rate']['lost_auc'] == 1
    assert records['attack_rate']['time_forfeit_auc'] == 1
    assert records['defensive_rate']['max_auc'] == .5
    assert all(r['training_rows'] == 40 for r in audit)
    strict = feature_list(frame, 'lf_ablated', audit)
    assert 'risk_rate' not in strict and 'attack_rate' not in strict
    assert 'defensive_rate' in strict and 'style_switch_rate' in strict
    assert 'clock_fraction_last' not in feature_list(frame)
    frame.loc[frame.split == 'test', ['risk_rate', 'status', 'result_score']] = [999, None, None]
    assert audit_outcome_proxies(frame) == audit
    # A missingness-only proxy is also removed (imputer exposes indicators).
    frame.loc[(frame.split == 'train') & frame.result_score.eq(0), 'style_switch_rate'] = np.nan
    assert {r['feature']: r for r in audit_outcome_proxies(frame)}['style_switch_rate']['exclude_strict']
    with pytest.raises(ValueError, match='LF provenance'):
        assert_no_lf_inputs(['clock_fraction_last'])


def test_outcome_strata_and_baseline_claims_cannot_hide_result_confound():
    f = pd.DataFrame(dict(result_score=[0, 0, 1, 1], weak_tilt_label=[1, 0, 1, 0],
                          weak_tilt_prob=[1, 0, 1, 0], predicted_weak_tilt_prob=[1, 1, 0, 0],
                          predicted_weak_tilt_score_regression=[100, 100, 0, 0]))
    strata = outcome_metrics(f, .5)
    assert all(m['roc_auc'] == .5 for m in strata.values())
    result = dict(test=dict(roc_auc=.8, pr_auc=.8, f1=.8), outcome_strata=dict(test=strata))
    baselines = [dict(model=name, test=dict(roc_auc=.5, pr_auc=.5, f1=.5), outcome_strata=dict(test=strata))
                 for name in ('class_prior', 'losing_streak', 'result_only')]
    assert not beats_baselines(result, baselines)  # Aggregates alone cannot establish utility.
    for m in result['outcome_strata']['test'].values():
        m['roc_auc'] = None
    assert not beats_baselines(result, baselines)


def test_lf_length_proxy_audit_all_variants_train_only():
    length = np.arange(10, 110, dtype=float)
    frame = pd.DataFrame(dict(split=['train'] * 100, result_score=[0, 1] * 50,
                              status=['mate', 'outoftime'] * 50,
                              lf_input__plies=length, clock_missing_fraction=1 / length,
                              phase_endgame_fraction=length / 110, defensive_rate=1.))
    held = frame.copy()
    held['split'] = 'validation'
    frame = pd.concat([frame, held], ignore_index=True)
    audit = audit_lf_proxies(frame)
    records = {r['feature']: r for r in audit}
    assert records['clock_missing_fraction']['rho'] == pytest.approx(-1)
    assert records['clock_missing_fraction']['lf_quantity'] == 'plies'
    assert records['phase_endgame_fraction']['exclude']
    assert all(r['training_rows'] == 100 for r in audit)
    for variant in ('full', 'no_history', 'lf_ablated', 'lf_ablated_no_history'):
        assert feature_list(frame, variant) == ['defensive_rate']
    frame.loc[frame.split.eq('validation'), ['lf_input__plies', 'clock_missing_fraction']] = [None, 999]
    assert audit_lf_proxies(frame) == audit


def test_lf_proxy_audit_missing_signals_status_and_selection():
    frame = pd.DataFrame(dict(split=['train'] * 100, lf_input__plies=np.arange(100),
                              lf_input__status=['mate'] * 50 + ['timeout'] * 50,
                              risk_rate=[np.nan] * 50 + [1.] * 50,
                              attack_rate=[1.] * 50 + [0.] * 50, defensive_rate=1.))
    audit = audit_lf_proxies(frame)
    records = {r['feature']: r for r in audit}
    assert records['risk_rate']['exclude'] and records['risk_rate']['representation'] == 'missing'
    assert records['attack_rate']['exclude']
    outcome = [dict(feature=c, exclude_strict=False) for c in ('risk_rate', 'attack_rate', 'defensive_rate')]
    assert not passes_audits(['risk_rate'], outcome, audit)
    assert not passes_audits(['unassessed'], outcome, audit)
    assert passes_audits(['defensive_rate'], outcome, audit)
    assert not passes_audits(['defensive_rate'], [dict(feature='defensive_rate', exclude_strict=True)], audit)


def test_abrupt_endings_do_not_conflict_with_average_play_or_later_recovery():
    row = dict(result_score=0, plies=50, final_eval_cp=0, final_eval_mate=None,
               last_adverse_distance=2, mean_accuracy=95, baseline_mean_accuracy_median=80,
               deviation_mean_cpl_z=0, adverse_events=0, rating_difference=-250,
               end_upper_ms=1000, next_start_ms=601000, next_deviation_mean_cpl_z=0)
    for status, positive in (('timeout', 'abandon'), ('resign', 'early_resign')):
        votes = dict(zip((lf.name for lf in LFS), vote(dict(row, status=status))))
        assert votes[positive] == 1
        assert all(votes[c] == ABSTAIN for c in ('normal_accuracy', 'calm_play', 'expected_loss', 'rest_and_recover'))
    # The same performance in an observed, conventionally completed game still
    # supports negatives, for any outcome. Short games do not establish them.
    for result in (0, .5, 1):
        votes = vote(dict(row, status='mate', result_score=result))
        assert votes[4] == votes[5] == votes[6] == 0
        assert vote(dict(row, status='mate', plies=20, result_score=result))[4:7] == [ABSTAIN] * 3
    assert vote(dict(row, status='timeout', final_eval_cp=-600))[0] == ABSTAIN


def test_failed_gate_is_loud_in_generated_report(weak_corpus):
    data, users = weak_corpus
    path = data / 'processed/features/games.parquet'
    frame = pd.read_parquet(path)
    # Suppress current post-loss behavioural LFs while retaining a timeout LF.
    frame.loc[frame.result_score.eq(1), 'deviation_mean_cpl_z'] = 0
    storage.write_frame(path, frame)
    moves_path = data / 'processed/features/moves.parquet'
    moves = pd.read_parquet(moves_path)
    moves.loc[moves.eval_after_cp.eq(-200), 'eval_after_cp'] = -100
    storage.write_frame(moves_path, moves)
    build(data, users)
    train(data, trees=2, threads=1, models=('random_forest',), variants=('full',))
    evaluate(data, bootstrap_repetitions=2)
    report = (data / 'processed/out/MODEL_REPORT.md').read_text()
    assert '**FAILED: label ≈ outcome' in report
    assert 'No beats-baselines claim' in report


def test_stale_weak_version_refused_by_train_and_evaluate(tmp_path):
    from tilt.labels.weak_labels import SPLIT_POLICY, WEAK_VERSION
    weak = dict(version=WEAK_VERSION - 1, split_policy=SPLIT_POLICY,
                salt_fingerprint=private_id('tilt-weak-model-salt-v1'))
    (tmp_path / 'processed' / 'out').mkdir(parents=True)
    (tmp_path / 'processed' / 'models').mkdir(parents=True)
    (tmp_path / 'processed/out/weak_manifest.json').write_text(json.dumps(weak))
    (tmp_path / 'processed/models/manifest.json').write_text(json.dumps(dict(status='complete', weak_manifest=weak)))
    with pytest.raises(ValueError, match='rebuild weak labels'):
        train(tmp_path)
    with pytest.raises(ValueError, match='Rebuild weak labels'):
        evaluate(tmp_path)
