"""Synthetic boundary checks; no real-data labels or held-out labels are read."""
from dataclasses import FrozenInstanceError, replace
from itertools import product

import numpy as np
import pandas as pd
import pytest

from tilt.features.features import robust
from tilt.labels import rules_v3 as r


def game(**kwargs):
    row = dict(game_id='g', raw_game_id='raw', player_id='existing-pseudonym',
               color='white', start_ms=1000000, end_ms=1100000, end_upper_ms=1100000,
               session_id='s', speed='blitz', rating=1500, result_score=0,
               status='mate', plies=60, exact_gap=10., last_clock_seconds=100.,
               initial_seconds=180., increment_seconds=0., own_moves=30,
               eval_moves=30, think_count=29)
    row.update({name: 1. for name in r.FEATURES})
    row.update(kwargs)
    return row


def prior(results, **kwargs):
    return [game(result_score=value, start_ms=900000 - i * 100000,
                 end_ms=950000 - i * 100000, **kwargs) for i, value in enumerate(results)]


def decision(**kwargs):
    row = game(level='strong', z_cpl=1., cpl_above_reference=1., n_fired=3, n_missing=0,
               **{e: 'fired' if e == 'E1' else 'not_fired' for e in r.EVIDENCE})
    row.update(kwargs)
    return row


def test_frozen_design_and_hash():
    with pytest.raises(FrozenInstanceError):
        r.DESIGN.own_min = 4
    assert len(r.DESIGN.hash) == 64
    assert replace(r.DESIGN, own_min=6).hash != r.DESIGN.hash


@pytest.mark.parametrize('results,expected', [([0, .5, 0, 1, 0], 2), ([.5, 0, .5, 0], 2),
                                           ([1, 0], 0), ([], 0)])
def test_loss_run_draws_and_session_start(results, expected):
    assert r.context(game(), prior(results))['L'] == expected


@pytest.mark.parametrize('results,expected', [([0, 0], 1 + 2 ** -.5),
                                           ([0, 0, 0], 1 + 2 ** -.5 + .5),
                                           ([0, 1, 0, 0], 1 + .5 + 2 ** -1.5)])
def test_decay_ll_lll_lwll(results, expected):
    assert r.context(game(), prior(results))['D'] == pytest.approx(expected)


def test_c2_absolute_threshold_fewer_than_five():
    assert r.context(game(), prior([0, 0, 0]))['C2']
    assert not r.context(game(), prior([0, 0]))['C2']
    assert not r.context(game(), prior([0, .5, 0, 1]))['C2']


@pytest.mark.parametrize('n', [0, 1, 2])
def test_c5_needs_three_prior_games_and_exact_gaps(n):
    assert not r.context(game(), prior([0] * n, exact_gap=20.))['C5']


def test_c5_nonstrict_middle_strict_overall_and_missing():
    p = prior([0, 1, 1])
    p[0]['exact_gap'], p[1]['exact_gap'] = 10., 20.
    assert r.context(game(exact_gap=10.), p)['C5']
    assert not r.context(game(exact_gap=20.), p)['C5']
    p[1]['exact_gap'] = np.nan
    assert not r.context(game(), p)['C5']
    p[1]['exact_gap'], p[0]['end_ms'] = 20., np.nan
    assert not r.context(game(), p)['C5']


@pytest.mark.parametrize('results,level', [([], 'none'), ([1], 'none'), ([0], 'weak'),
                                        ([0, 0, 0], 'strong'), ([1, 0], 'stale')])
def test_context_levels(results, level):
    assert r.context(game(), prior(results))['level'] == level


def test_rating_context_first_game_and_threshold():
    assert r.context(game(), [])['rating_delta'] == 0
    assert not r.context(game(), [])['C4']
    assert r.context(game(rating=1470), prior([1]))['C4']
    assert not r.context(game(rating=1471), prior([1]))['C4']


@pytest.mark.parametrize('e,name,sign', [(1, 'cpl_mean_w300', 1), (2, 'blunders_per20', 1),
                                      (3, 'think_frac_median', -1), (4, 'think_cv', 1)])
@pytest.mark.parametrize('state', ['fired', 'not_fired', 'missing'])
def test_e1_to_e4_states(e, name, sign, state):
    row = {f'z_{f}': 0. for f in r.FEATURES}
    row['z_' + name] = sign if state == 'fired' else np.nan if state == 'missing' else 0.
    assert r.evidence(row)[f'E{e}'] == state


@pytest.mark.parametrize('state,zs', [('fired', [1., 1., 1.]), ('not_fired', [0., 1., 1.]),
                                    ('missing', [2., np.nan, 2.])])
def test_e5_states(state, zs):
    row = {f'z_{f}': 0. for f in r.FEATURES}
    row.update(dict(zip(['z_' + n for n in r.FEATURES[4:]], zs)))
    assert r.evidence(row)['E5'] == state


def terminal(cp=np.nan, mate=np.nan, color='white'):
    return dict(eval_after_cp=cp, eval_after_mate=mate, color=color)


@pytest.mark.parametrize('cp,color,expected', [(-100, 'white', 'fired'), (500, 'black', 'not_fired'),
                                            (-500, 'black', 'fired')])
def test_e6_cp_point_of_view(cp, color, expected):
    assert r.e6(game(status='resign'), [terminal(cp=cp, color=color)])[0] == expected


@pytest.mark.parametrize('mate,color,expected', [(2, 'white', 'fired'), (-2, 'white', 'not_fired'),
                                              (2, 'black', 'not_fired'), (-2, 'black', 'fired')])
def test_e6_mate_point_of_view(mate, color, expected):
    assert r.e6(game(status='resign'), [terminal(mate=mate, color=color)])[0] == expected


def test_e6_missing_penultimate_and_status_semantics():
    assert r.e6(game(status='resign'), [terminal(), terminal()])[0] == 'missing'
    assert r.e6(game(status='resign'), [terminal(), terminal(cp=0, color='black')])[0] == 'fired'
    assert r.e6(game(status='timeout'), [])[0] == 'fired'
    assert r.e6(game(status='outoftime', last_clock_seconds=36), [])[0] == 'fired'
    assert r.e6(game(status='outoftime', last_clock_seconds=35.99), [])[0] == 'not_fired'
    assert r.e6(game(status='outoftime', last_clock_seconds=np.nan), [])[0] == 'not_fired'
    assert r.e6(game(status='outoftime', increment_seconds=np.nan), [])[0] == 'not_fired'
    assert r.e6(game(status='timeout', result_score=1), [])[0] == 'not_fired'


@pytest.mark.parametrize('gap,state', [(10., 'fired'), (20., 'fired'), (20.01, 'not_fired'), (61., 'not_fired')])
def test_e7_thresholds(gap, state):
    current = game()
    nxt = game(start_ms=current['end_ms'] + gap * 1000)
    assert r.e7(current, nxt, [20.] * 10)[0] == state


def test_e7_missing_collection_edge_other_session_and_exact_end():
    assert r.e7(game(), None, [20.] * 10)[0] == 'missing'
    assert r.e7(game(), game(session_id='new'), [20.] * 10)[0] == 'not_fired'
    assert r.e7(game(), game(), [20.] * 9)[0] == 'missing'
    assert r.e7(game(end_ms=np.nan), game(), [20.] * 10)[0] == 'missing'
    assert r.e7(game(result_score=.5), None, [])[0] == 'not_fired'
    assert r.e7(game(), game(session_id='new'), [20.] * 9)[0] == 'missing'


@pytest.mark.parametrize('level,expected', [
    ('none', ['NOT', 'NOT', 'ABSTAIN', 'ABSTAIN', 'ABSTAIN', 'ABSTAIN']),
    ('stale', ['NOT', 'ABSTAIN', 'ABSTAIN', 'ABSTAIN', 'ABSTAIN', 'ABSTAIN']),
    ('weak', ['NOT', 'ABSTAIN', 'ABSTAIN', 'TILT', 'ABSTAIN', 'ABSTAIN']),
    ('strong', ['NOT', 'ABSTAIN', 'TILT', 'TILT', 'ABSTAIN', 'ABSTAIN'])])
def test_every_truth_table_cell(level, expected):
    cells = [(1, 0, -1), (1, 0, 1), (2, 0, 1), (3, 0, 1), (2, 0, 0), (1, 1, 1)]
    for (fired, missing, z), label in zip(cells, expected):
        assert r.combine(decision(level=level, n_fired=fired, n_missing=missing, z_cpl=z))['label'] == label


def test_won_game_rule():
    assert r.combine(decision(result_score=1, n_fired=2))['label'] == 'ABSTAIN'
    assert r.combine(decision(result_score=1, level='weak'))['label'] == 'ABSTAIN'
    assert r.combine(decision(result_score=1, E1='not_fired'))['label'] == 'ABSTAIN'
    assert r.combine(decision(result_score=1))['label'] == 'TILT'
    assert r.combine(decision(result_score=1, E1='not_fired', E2='fired'))['label'] == 'TILT'


def test_combination_invariants_exhaustive():
    for level, z, fired, missing, result in product(
            ['none', 'stale', 'weak', 'strong'], [-1, 0, 1], range(8), range(8), [0, .5, 1]):
        if fired + missing > 7:
            continue
        label = r.combine(decision(level=level, z_cpl=z, n_fired=fired, n_missing=missing,
                                   result_score=result))['label']
        if label == 'TILT':
            assert z > 0 and level in ('weak', 'strong')


@pytest.mark.parametrize('kwargs,reason', [({'own_moves': 4}, 'short_game'),
                                        ({'eval_moves': 4}, 'no_eval'),
                                        ({'z_cpl': np.nan}, 'no_baseline')])
def test_eligibility_reason_precedence(kwargs, reason):
    assert r.combine(decision(**kwargs)) == dict(eligible=False, label='ABSTAIN', abstain_reason=reason)


def history(n, **kwargs):
    return pd.DataFrame([game(game_id=f'g{i}', raw_game_id=f'raw{i}', start_ms=i * 10000,
                              end_ms=i * 10000 + 5000, end_upper_ms=i * 10000 + 5000,
                              **kwargs) for i in range(n)])


def test_prior_only_bucket_pooled_and_strict_end():
    h = history(30)
    row = game(start_ms=205000)
    ix, kind = r.reference_indices(h, row)
    assert kind == 'bucketed' and len(ix) == 20
    assert (h.loc[ix].end_upper_ms < row['start_ms']).all()
    assert 20 not in ix  # equal end is not eligible
    row['plies'] = 20
    ix, kind = r.reference_indices(h, row)
    assert kind == 'pooled' and len(ix) == 20
    assert r.reference_indices(h, game(start_ms=45000))[1] == 'none'
    assert r.reference_indices(h, game(start_ms=65000), 'v3b')[1] == 'none'
    assert r.reference_indices(h, game(start_ms=65000), 'v3')[1] == 'pooled'


def test_bucket_search_precedes_cap_and_cap_is_200():
    h = history(300)
    h.loc[30:, 'plies'] = 20
    ix, kind = r.reference_indices(h, game(start_ms=10000000, plies=60))
    assert kind == 'bucketed' and len(ix) == 30  # old bucket games retained
    ix, kind = r.reference_indices(h, game(start_ms=10000000, plies=20))
    assert len(ix) == 200 and min(ix) == 100


def test_robust_matches_existing_helper_and_feature_missing():
    h = history(6)
    h.loc[:, 'cpl_mean_w300'] = [1., 2., 3., 4., 5., 6.]
    row = game(cpl_mean_w300=30.)
    actual = r.baseline(row, h, 'pooled')
    expected = robust(row, h.to_dict('records'), dict(r.DESIGN.floors), 5)
    for name in r.FEATURES:
        assert actual['z_' + name] == pytest.approx(expected['deviation_' + name + '_z'])
    h.loc[:1, 'risk_rate'] = np.nan
    assert np.isnan(r.baseline(row, h, 'pooled')['z_risk_rate'])


def test_fallback_percentiles_linear_and_sign():
    h = history(20)
    h.loc[:, 'cpl_mean_w300'] = np.arange(20.)
    row = game(cpl_mean_w300=15.2)
    b = r.baseline(row, h, 'bucketed', 'v3b')
    assert b['cpl_mean_w300_p80'] == pytest.approx(15.2)
    assert b['cpl_mean_w300_p20'] == pytest.approx(3.8)
    row['cpl_mean_w300'] = b['cpl_mean_w300_p80']
    ev = r.evidence({**row, **b}, 'v3b')
    assert ev['E1'] == 'fired'
    assert r.combine(decision(z_cpl=1, cpl_above_reference=0), 'v3b')['label'] == 'ABSTAIN'
    assert r.combine(decision(z_cpl=-1, cpl_above_reference=1), 'v3b')['label'] == 'TILT'


@pytest.mark.parametrize('i,name', list(enumerate(r.FEATURES[:4], 1)))
def test_fallback_each_evidence_quantile_and_missing(i, name):
    row = game()
    row.update(r.baseline(row, history(20), 'bucketed', 'v3b'))
    assert r.evidence(row, 'v3b')[f'E{i}'] == 'fired'  # equality included
    row[name] = np.nan
    assert r.evidence(row, 'v3b')[f'E{i}'] == 'missing'


def test_fallback_e5_needs_two_of_three():
    row = game()
    row.update(r.baseline(row, history(20), 'bucketed', 'v3b'))
    assert r.evidence(row, 'v3b')['E5'] == 'fired'
    row['risk_rate'], row['attack_rate'] = 0., 0.
    assert r.evidence(row, 'v3b')['E5'] == 'not_fired'
    row['risk_rate_p80'] = np.nan
    assert r.evidence(row, 'v3b')['E5'] == 'missing'


def test_vectorised_aggregates_population_std_flags_and_windows():
    games = pd.DataFrame([game()])
    moves = pd.DataFrame([dict(game_id='raw', color='white', ply=2 * i + 1,
                               cpl=600. if i == 0 else 0., judgement='blunder' if i == 0 else 'good',
                               think_seconds=float(i), risk=i % 2, attack=False,
                               sacrifice_heuristic=False) for i in range(5)])
    a = r.aggregates(games.drop(columns=list(r.FEATURES) + ['own_moves', 'eval_moves', 'think_count']), moves).iloc[0]
    assert a.own_moves == 5 and a.cpl_mean_w300 == 60. and a.blunders_per20 == 4.
    assert a.think_cv == pytest.approx(np.std(np.arange(5.)) / 2.)
    assert a.think_frac_median == pytest.approx(2. / 180.)
    assert a.risk_rate == .4
    games.loc[:, 'increment_seconds'] = np.nan
    a = r.aggregates(games.drop(columns=list(r.FEATURES) + ['own_moves', 'eval_moves', 'think_count']), moves).iloc[0]
    assert np.isnan(a.think_frac_median)


@pytest.mark.parametrize('part', ['validation', 'test', 'purged_shared_game', 'purged_crossing_cutoff'])
def test_held_out_and_purged_targets_are_never_labelled_or_scored(part):
    targets = pd.DataFrame([dict(game_id='g', color='white', split=part)])
    with pytest.raises(ValueError, match='train'):
        r.label_train(pd.DataFrame(), targets, {})
    with pytest.raises(ValueError, match='train'):
        r.gates(targets)
    with pytest.raises(ValueError, match='train'):
        r.report_stats(targets, pd.DataFrame())


def test_train_targets_only_nontrain_feature_history_and_session_boundary():
    h = history(25)
    h.loc[:10, 'session_id'] = 'old'
    targets = h.loc[[11, 20], r.KEYS].assign(split='train')
    labels = r.label_train(h, targets, {})
    assert len(labels) == 2 and set(labels.game_id) == set(targets.game_id)
    first = labels[labels.game_id.eq('g11')].iloc[0]
    assert first.L == 0 and first.level == 'none' and first.label != 'TILT'
    assert labels.baseline_latest_end_ms.notna().all()
    assert 'player' not in labels and 'raw_game_id' not in labels


def test_rating_check_sign_zero_change_and_failure():
    h = history(4)
    h['rated'] = True
    h['rating'] = [1500, 1490, 1480, 1470]
    a = {'by_player': h[r.KEYS].assign(split='train')}
    checks = r.rating_check(h, a)
    assert checks['by_player']['share'] == 1.
    h.loc[1, 'rating'] = 1500
    with pytest.raises(r.PreflightError, match='rating sign'):
        r.rating_check(h, a)


def test_g2_sparse_merge_and_undefined_gates_fail_closed():
    f = pd.DataFrame(dict(plies=[10, 50, 90], label=['NOT', 'TILT', 'NOT']))
    result = r.length_buckets(f)
    assert len(result['merges']) == 2 and len(result['buckets']) == 1 and result['gap'] == 0.
    f = pd.DataFrame([dict(split='train', plies=60, label='NOT', eligible=True,
                           L=0, n_fired=0, prev_lost=False, result_score=0,
                           **{e: 'not_fired' for e in r.EVIDENCE})])
    gates = r.gates(f)
    assert not gates['G1']['passed'] and not gates['G3b']['passed']
    assert not gates['G6']['passed'] and not gates['G7']['passed']


def test_variant_selection_ties_and_split_order():
    def variant(a, b):
        return {s: {f'G{i}': dict(passed=i >= n) for i in range(4)}
                for s, n in [('by_player', a), ('by_time', b)]}
    assert r.select_variant({'v3': variant(2, 1), 'v3b': variant(1, 3)}) == 'v3b'
    assert r.select_variant({'v3': variant(1, 1), 'v3b': variant(1, 2)}) == 'v3'
    assert r.select_variant({'v3b': variant(1, 1), 'v3': variant(1, 1)}) == 'v3'
