"""Synthetic checks for the frozen deterministic post-loss protocol."""
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from tilt.labels import postloss as p

PARAMS = dict(deteriorated_z=1.5, fast_z=1., steady_z=1., adverse_rate=.25, gap_seconds=120)
SPECS = [dict(min_plies=20, min_move_count=10, bucket_edges=[20, 40, 60, 80, 'inf'],
              bucket_labels=['20–39', '40–59', '60–79', '>=80']),
         dict(min_plies=40, min_move_count=20, bucket_edges=[40, 60, 80, 'inf'],
              bucket_labels=['40–59', '60–79', '>=80'])]
GATES = dict(G1={}, G2=dict(min_tilt_per_bucket=30, min_not_per_bucket=100,
                          min_total_tilt=300, min_labelled=1200),
             G3=dict(min_common_gate_coverage=.5), G4=dict(max_direction_free_plies_auc=.60),
             G5=dict(max_bucket_tilt_rate_range=.15), G6=dict(max_pooled_oof_auc=.62),
             G7=dict(previous_same_session_loss_share_tilt=1.,
                     previous_same_session_loss_share_not_tilt=1., max_conflicts=0))


def row(**patch):
    return dict(plies=40, move_count=20, start_ms=120000, previous_end_upper_ms=0,
                previous_result_score=0., previous_same_session=True,
                deviation_mean_cpl_z=2., mean_think=6.5,
                baseline_mean_think_median=10., adverse_events=5.) | patch


@pytest.mark.parametrize('spec', SPECS)
def test_classes_at_every_integer_length_and_provenance(spec):
    assert p.structural_check(spec, PARAMS)['passed']
    for plies in [*range(0, 1001), 1000000]:
        own = max(spec['min_move_count'], plies // 2)
        pos = p.vote(row(plies=plies, move_count=own), spec, PARAMS)
        neg = p.vote(row(plies=plies, move_count=own, deviation_mean_cpl_z=-100., adverse_events=0), spec, PARAMS)
        if plies < spec['min_plies']:
            assert pos == neg == [-1] * 3
        else:
            assert 1 in pos and 0 not in pos
            assert 0 in neg and 1 not in neg


@pytest.mark.parametrize('spec', SPECS)
@pytest.mark.parametrize('key', p.COMMON_CURRENT + p.COMMON_PAST)
@pytest.mark.parametrize('bad', [None, pd.NA, np.nan, np.inf, -np.inf])
def test_missing_or_invalid_common_evidence_abstains(spec, key, bad):
    assert p.vote(row(**{key: bad}), spec, PARAMS) == [-1] * 3


@pytest.mark.parametrize('spec', SPECS)
def test_common_gate_boundaries_apply_to_both_classes(spec):
    for z in [2., 0.]:
        base = row(plies=spec['min_plies'], move_count=spec['min_move_count'], deviation_mean_cpl_z=z, adverse_events=0)
        for gap in [0, 120]:
            assert p.common_gate(base | dict(start_ms=gap * 1000), spec, PARAMS)
        for patch in [dict(plies=spec['min_plies'] - 1), dict(move_count=spec['min_move_count'] - 1),
                      dict(start_ms=-1), dict(start_ms=120001), dict(previous_result_score=1),
                      dict(previous_same_session=False), dict(previous_same_session='true')]:
            assert p.vote(base | patch, spec, PARAMS) == [-1] * 3
        assert p.vote({k: v for k, v in base.items() if k != 'move_count'}, spec, PARAMS) == [-1] * 3


def test_deterministic_rules_and_boundaries():
    s = SPECS[0]
    assert p.vote(row(), s, PARAMS) == [1, 1, -1]
    assert p.vote(row(deviation_mean_cpl_z=1.5, mean_think=6.50001), s, PARAMS) == [1, -1, -1]
    assert p.vote(row(deviation_mean_cpl_z=1.), s, PARAMS) == [-1, 1, -1]
    assert p.vote(row(deviation_mean_cpl_z=1., mean_think=7.), s, PARAMS) == [-1, -1, -1]
    assert p.vote(row(deviation_mean_cpl_z=.99999), s, PARAMS) == [-1, -1, 0]
    assert p.vote(row(deviation_mean_cpl_z=-100.), s, PARAMS) == [-1, -1, 0]
    assert p.vote(row(deviation_mean_cpl_z=0., adverse_events=5.00001), s, PARAMS) == [-1] * 3
    for bad in [None, np.nan, np.inf, -np.inf]:
        assert p.vote(row(deviation_mean_cpl_z=bad), s, PARAMS) == [-1] * 3
    for key, values in {'mean_think': [None, np.nan, np.inf, -1, 6.50001],
                        'baseline_mean_think_median': [None, np.nan, np.inf, 0, -1]}.items():
        for bad in values:
            assert p.vote(row(deviation_mean_cpl_z=1., **{key: bad}), s, PARAMS) == [-1] * 3
            assert p.vote(row(**{key: bad}), s, PARAMS)[0] == 1  # independent LF evidence
    for bad in [None, np.nan, np.inf, -1]:
        assert p.vote(row(deviation_mean_cpl_z=0., adverse_events=bad), s, PARAMS) == [-1] * 3
    assert p.aggregate([[1, -1, 0], [-1, -1, 0], [-1, -1, -1], [1, 1, -1]]).tolist() == [1, 0, -1, 1]


def test_provenance_blocks_current_outcome_status_terminal_and_future_reads():
    allowed = set(p.COMMON_CURRENT + p.COMMON_PAST)
    allowed.update(k for lf in p.LF_PROVENANCE.values() for side in ('current', 'past') for k in lf[side])
    class Guard(dict):
        def get(self, key, default=None):
            assert key in allowed
            return super().get(key, default)
        def __getitem__(self, key):
            assert key in allowed
            return super().__getitem__(key)
    for spec in SPECS:
        for z in [-100., .999, 1., 1.5, 2., np.nan]:
            base = row(deviation_mean_cpl_z=z)
            expected = p.vote(Guard(base), spec, PARAMS)
            for value in [None, 0., .5, 1., 'resign', 'mate', np.inf]:
                extras = dict(result_score=value, status=value, final_eval_cp=value, final_eval_mate=value,
                              next_deviation_mean_cpl_z=value, next_start_ms=value, end_upper_ms=value,
                              prior_session_loss_run=value, session_shrinking_gaps=value)
                assert p.vote(Guard(base | extras), spec, PARAMS) == expected
    assert all(not lf['future'] for lf in p.LF_PROVENANCE.values())


def frozen(tmp_path):
    design = tmp_path / 'design_v2_L2.json'
    design.write_text(json.dumps(dict(frozen_at_utc='2026-11-15T00:00:00+00:00')))
    digest = hashlib.sha256(design.read_bytes()).hexdigest()
    design.with_suffix('.sha256').write_text(f'{digest}  {design.name}\nUTC 2026-11-15T00:00:00+00:00\n')
    return design, digest


def test_hash_enforced_before_any_data_load(tmp_path, monkeypatch):
    design, digest = frozen(tmp_path)
    assert p.verify_design(design)[1] == digest
    design.write_text(design.read_text() + ' ')
    def no_load(*args):
        pytest.fail('Data access before hash verification')
    monkeypatch.setattr(p, 'load_train_with_groups', no_load)
    with pytest.raises(ValueError, match='hash mismatch'):
        p.run(tmp_path, tmp_path / 'out', design)
    assert not (tmp_path / 'out').exists()


def test_uses_l1_predicate_loader_and_train_only_group_projection(tmp_path, monkeypatch):
    source = tmp_path / 'fixture.parquet'
    pd.DataFrame(dict(split=['train', 'validation', 'test'], player_id=['synthetic-a', 'synthetic-b', 'synthetic-c'],
                      weak_tilt_label=[0, 1, 1], lf_input__plies=[40, 999, 888],
                      model_feature=[1, 9, 9])).to_parquet(source)
    original = pd.read_parquet
    calls = []
    def read(path, **kwargs):
        assert kwargs['filters'] == [('split', '==', 'train')]
        assert 'model_feature' not in kwargs['columns']
        calls.append(kwargs['columns'])
        return original(path, **kwargs)
    monkeypatch.setattr(pd, 'read_parquet', read)
    loaded = p.load_train_with_groups(source)
    assert len(calls) == 2
    assert loaded.player_id.tolist() == ['synthetic-a']
    assert loaded.lf_input__plies.tolist() == [40]


@pytest.mark.parametrize('parts', [None, ['validation'], ['test'], ['train', 'test']])
def test_non_train_rejected_before_evidence_or_summary(parts):
    frame = pd.DataFrame({'x': [1]}) if parts is None else pd.DataFrame({'split': parts})
    for fn in [lambda: p.evidence(frame, SPECS[0], PARAMS), lambda: p.summary(frame, SPECS[0], PARAMS, 42)]:
        with pytest.raises(ValueError, match='TRAIN'):
            fn()


def test_g6_manual_crossfit_no_player_leakage_and_training_only_edges():
    # Each player has a distinct length distribution; no hold-fold quantile use.
    players = np.repeat(np.arange(10), 12)
    plies = 20 + players * 20 + np.tile(np.arange(12), 10)
    y = (np.arange(len(plies)) % 3 == 0).astype(int)
    r = p.decile_oof(plies, y, players, 42)
    manual = np.full(len(y), np.nan)
    for detail, (train, hold) in zip(r['folds'], GroupKFold(n_splits=5).split(plies, y, players)):
        assert not set(players[train]) & set(players[hold])
        edges = np.unique(np.quantile(plies[train], np.arange(1, 10) / 10, method='linear'))
        assert detail['internal_edges'] == edges.tolist()
        fit_bins = np.digitize(plies[train], edges, right=False)
        rates = [float(y[train][fit_bins == b].mean()) if (fit_bins == b).any() else float(y[train].mean()) for b in range(len(edges) + 1)]
        np.testing.assert_allclose(detail['tilt_rates'], rates)
        manual[hold] = np.array(rates)[np.digitize(plies[hold], edges, right=False)]
    assert r['auc'] == roc_auc_score(y, manual)
    assert p.decile_oof(plies, y, players, 999) == r  # seed has no effect
    with pytest.raises(ValueError, match='G6 impossible'):
        p.decile_oof(plies[:12], y[:12], players[:12], 42)


def test_g6_ties_empty_bin_and_unbounded_tails():
    edges, rates, counts = p.fit_deciles(np.array([40] * 10), np.array([0, 1] * 5))
    assert edges.tolist() == [40.]
    assert counts.tolist() == [0, 10]
    assert rates.tolist() == [.5, .5]
    assert rates[np.digitize([20, 40, 1000], edges, right=False)].tolist() == [.5] * 3


def test_g6_stops_on_single_class_training_fold_and_missing_groups():
    players = np.repeat(np.arange(5), 10)
    plies = np.arange(50) + 20
    y = (players == 0).astype(int)
    with pytest.raises(p.G6CannotCompute, match='training fold .*only one class'):
        p.decile_oof(plies, y, players)
    with pytest.raises(p.G6CannotCompute, match='only one class'):
        p.decile_oof(plies, np.zeros(50), players)
    with pytest.raises(p.G6CannotCompute, match='missing player_id'):
        p.decile_oof(plies, y, np.array([None] + players[1:].tolist(), dtype=object))


def test_sensitivity_conflicts_tilt_wins_and_gap_changes_population():
    f = pd.DataFrame([dict(split='train', **{p.LF_INPUT_PREFIX + k: v for k, v in
        row(deviation_mean_cpl_z=.8, adverse_events=0).items()})])
    assert p.sensitivity_summary(f, SPECS[0], PARAMS)['tilt'] == 0
    r = p.sensitivity_summary(f, SPECS[0], PARAMS | dict(fast_z=.75))
    assert r['conflicts'] == r['tilt'] == 1 and r['not_tilt'] == 0
    assert r['direction_free_auc'] is None and r['bucket_tilt_rate_range'] is None
    assert p.sensitivity_summary(f, SPECS[0], PARAMS | dict(gap_seconds=60))['labelled'] == 0
    assert set(r) == {'labelled', 'tilt', 'not_tilt', 'tilt_rate', 'direction_free_auc',
                      'bucket_tilt_rate_range', 'conflicts'}


def test_fallback_uses_only_declared_trigger_failures():
    d = dict(fallback=dict(trigger_gates=['G2', 'G4', 'G5', 'G6']))
    passing = {f'G{i}': True for i in range(1, 8)}
    for gate in passing:
        results = dict(by_player=dict(gates=passing), by_time=dict(gates=passing | {gate: False}))
        expected = ['by_time:' + gate] if gate in d['fallback']['trigger_gates'] else []
        assert p.fallback_reasons(results, d) == expected


def test_summary_population_denominators_and_report_only_outcomes():
    records = []
    for player in range(5):
        for plies in [20, 40, 60, 80]:
            for z in [2., 0., 1.]:
                ctx = row(plies=plies, move_count=max(10, plies // 2), adverse_events=0,
                          deviation_mean_cpl_z=z, mean_think=9.)
                records.append(dict(split='train', player_id=f'fixture{player}', weak_tilt_label=int(z == 2.),
                                    **{p.LF_INPUT_PREFIX + k: v for k, v in (ctx | dict(rating=1500, result_score=1)).items()}))
    f = pd.DataFrame(records)
    r = p.summary(f, SPECS[0], PARAMS, 42)
    assert r['labelled'] == 40 and r['common_gate_rows'] == 60
    assert r['coverage_common_gate'] == r['coverage_all_train'] == 2 / 3
    assert r['conflicts'] == 0
    assert r['population']['tilt']['share'] == r['population']['not_tilt']['share'] == 1
    assert r['agreement_v1']['agreement'] == 1
    assert r['agreement_v1']['lost_labels'] == 20 and r['agreement_v1']['newly_labelled'] == 0
    assert r['agreement_v1']['counts'] == dict(v1_0_v2_0=20, v1_0_v2_1=0, v1_1_v2_0=0, v1_1_v2_1=20)
    assert r['current_result']['win']['labelled'] == 40
    assert r['rating_band']['1200–1599']['labelled'] == 40
    changed = f.copy()
    changed[p.LF_INPUT_PREFIX + 'result_score'] = 0
    changed[p.LF_INPUT_PREFIX + 'rating'] = 2100
    r2 = p.summary(changed, SPECS[0], PARAMS, 42)
    for key in ['labelled', 'tilt', 'not_tilt', 'g6', 'direction_free_auc', 'buckets']:
        assert r2[key] == r[key]


def test_gates_thresholds_and_undefined_fail_closed():
    r = dict(structure=dict(passed=True), buckets={'one': dict(tilt=300, not_tilt=900)},
             tilt=300, labelled=1200, coverage_common_gate=.5, direction_free_auc=.60,
             bucket_tilt_rate_range=.15, g6=dict(auc=.62), conflicts=0,
             population=dict(tilt=dict(share=1.), not_tilt=dict(share=1.)))
    assert all(p.score_gates(r, GATES).values())
    for gate, patch in [('G2', dict(buckets={'one': dict(tilt=0, not_tilt=0)})),
                        ('G3', dict(coverage_common_gate=None)),
                        ('G4', dict(direction_free_auc=None)),
                        ('G5', dict(bucket_tilt_rate_range=None)),
                        ('G6', dict(g6=dict(auc=None))), ('G7', dict(conflicts=1))]:
        assert not p.score_gates(r | patch, GATES)[gate]


def protocol_fixture(tmp_path):
    grid = [dict(id=f'{key}={value}', **(PARAMS | {key: value}))
            for key, values in dict(deteriorated_z=[1.25, 1.75], fast_z=[.75, 1.25],
                steady_z=[.75, 1.25], adverse_rate=[.2, .3], gap_seconds=[60, 180]).items()
            for value in values]
    design = dict(frozen_at_utc='2026-11-15T00:00:00+00:00', scope='synthetic TRAIN', seed=42,
                  designs=dict(zip(['postloss20', 'postloss40'], SPECS)), parameters=PARAMS,
                  gates=GATES, fallback=dict(trigger_gates=['G2', 'G4', 'G5', 'G6']),
                  sensitivity=dict(applies_to=['postloss20'], grid=grid))
    path = tmp_path / 'design_v2_L2.json'
    path.write_text(json.dumps(design))
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    path.with_suffix('.sha256').write_text(f'{digest}  {path.name}\nUTC {design["frozen_at_utc"]}\n')
    return path


def balanced_frame(fail_short_bucket=False):
    records = []
    for player in range(5):
        for plies in [20, 40, 60, 80]:
            for index in range(100):
                tilt = index < 25 and not (fail_short_bucket and plies == 20)
                ctx = row(plies=plies, move_count=plies // 2, adverse_events=0,
                          deviation_mean_cpl_z=2. if tilt else 0., rating=1500, result_score=1.)
                records.append(dict(split='train', player_id=f'fixture{player}', weak_tilt_label=np.nan,
                    **{p.LF_INPUT_PREFIX + k: v for k, v in ctx.items()}))
    return pd.DataFrame(records)


@pytest.mark.parametrize('fallback', [False, True])
def test_frozen_run_fallback_authorisation_and_sensitivity_scope(tmp_path, monkeypatch, fallback):
    design = protocol_fixture(tmp_path)
    frame = balanced_frame(fail_short_bucket=fallback)
    monkeypatch.setattr(p, 'load_train_with_groups', lambda _: frame.copy())
    result = p.run(tmp_path, tmp_path / 'aggregates', design)
    assert result['fallback_computed'] is fallback
    assert result['verdict'] == ('postloss40 accepted' if fallback else 'postloss20 accepted')
    for split in ('by_player', 'by_time'):
        r = result['designs']['postloss20'][split]
        assert len(r['sensitivity']) == 10
        assert r['agreement_v1']['newly_labelled'] == r['labelled']
        assert r['agreement_v1']['lost_labels'] == 0
        for variant in r['sensitivity']:
            params = variant['parameters']
            assert sum(params[k] != v for k, v in PARAMS.items()) == 1
        if fallback:
            assert result['designs']['postloss40'][split]['sensitivity'] == []
        else:
            assert 'postloss40' not in result['designs']
    stored = json.loads((tmp_path / 'aggregates/results.json').read_text())
    assert stored == json.loads(json.dumps(result))  # JSON represents provenance tuples as arrays.
    with pytest.raises(FileExistsError):
        p.run(tmp_path, tmp_path / 'aggregates', design)


def test_g6_impossible_stops_run_and_records_failure(tmp_path, monkeypatch):
    design = protocol_fixture(tmp_path)
    frame = balanced_frame()
    frame['player_id'] = 'single-synthetic-player'
    monkeypatch.setattr(p, 'load_train_with_groups', lambda _: frame.copy())
    result = p.run(tmp_path, tmp_path / 'aggregates', design)
    assert result['stopped']['gate'] == 'G6'
    assert result['designs']['postloss20']['by_player']['gates'] == {'G6': False}
    assert not result['fallback_computed']
    assert 'by_time' not in result['designs']['postloss20']
