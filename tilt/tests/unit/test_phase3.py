import numpy as np
import pandas as pd
import pytest

from tilt.evaluation import phase1, phase3


def frame(n=60, seed=0):
    rng = np.random.default_rng(seed)
    data = {c: rng.normal(size=n) for c in set(phase3.M3 + phase3.USED)}
    data['risk_rate'][:3] = np.nan            # M3 column with missing values: keeps its indicator
    data['attack_trend_3w'][:5] = np.nan      # group B: no indicator
    return pd.DataFrame(data)


def test_m3_design_is_the_phase1_matrix():
    f, train = frame(), np.arange(40)
    assert np.allclose(phase3.design(f, phase3.M3, train), phase1.design(f, phase3.M3, train, True))


def test_group_b_has_no_missing_indicator():
    f, train = frame(), np.arange(40)
    columns = phase3.VARIANTS['P3-B']
    x = phase3.design(f, columns, train)
    # values for 11 columns + one indicator (risk_rate); none for attack_trend_3w
    assert x.shape[1] == len(columns) + 1


def test_replacement_keeps_positions():
    r = phase3.VARIANTS['P3-R']
    assert len(r) == len(phase3.M3)
    for old, new in zip(phase3.M3, r):
        assert new == (old + '_p40' if old in phase3.RATES else old)
    assert phase3.VARIANTS['P3-DB'] == phase3.M3 + phase3.D + phase3.B


def test_excluded_features_are_never_used():
    used = {c for cols in phase3.VARIANTS.values() for c in cols}
    assert not used & {'style_entropy', 'behavior_persistence'}
    assert not {c for c in used if c.endswith(('_delta_personal', '_z_personal'))}


def test_bootstrap_secondary_filters_after_drawing_players():
    players = np.repeat(np.arange(20), 5)
    y = np.tile([0, 1, 0, 0, 1], 20)
    long = np.tile([True, True, False, False, False], 20)
    p = np.linspace(0, 1, 100)
    out = phase3.bootstrap(players, y, {'M3': p, 'P3-D': p[::-1]}, long, repetitions=50)
    assert out['skipped'] == dict(primary=0, secondary=0)
    assert out['paired']['secondary']['P3-D']['ci'] is not None
    only_negative = phase3.bootstrap(players, y, {'M3': p, 'P3-D': p}, long & (y == 0), repetitions=10)
    assert only_negative['skipped']['secondary'] == 10


def results(m3=(.449, .370), deltas=None, secondary=None, ci_low=.01, sec_ci=(.001, .02)):
    deltas = deltas or {}
    secondary = secondary or {}
    out = {}
    for i, s in enumerate(phase3.SPLITS):
        validation = {}
        for name in phase3.VARIANTS:
            d = deltas.get(name, (0, 0))[i]
            sd = secondary.get(name, (0, 0))[i]
            validation[name] = dict(primary=dict(pr_auc=m3[i] + d), secondary=dict(pr_auc=.14 + sd))
        paired = {k: {n: dict(mean=0, ci=list(ci)) for n in phase3.VARIANTS if n != 'M3'}
                  for k, ci in (('primary', (ci_low, .1)), ('secondary', sec_ci))}
        out[s] = dict(validation=validation, bootstrap=dict(paired=paired))
    return out


def test_reproduction_failure_stops_every_rule():
    decision = phase3.decide(results(m3=(.46, .370)))
    assert decision['main'] is None and not decision['m3_reproduction']['ok']


def test_gain_only_from_short_games_is_not_accepted():
    r = results(deltas={'P3-D': (.06, .01)}, secondary={'P3-D': (-.01, .01)})
    decision = phase3.decide(r)
    assert decision['variants']['P3-D']['verdict'].startswith('gain from short games')
    assert decision['main'] in ('M3', 'P3-R')


def test_fewer_columns_wins_when_close():
    r = results(deltas={'P3-B': (.07, .02), 'P3-DB': (.09, .03)}, secondary={'P3-B': (.01, .01), 'P3-DB': (.01, .01)})
    decision = phase3.decide(r)
    assert set(decision['accepted']) == {'P3-B', 'P3-DB'} and decision['main'] == 'P3-B'


def test_replacement_rule():
    ok = phase3.decide(results(deltas={'P3-R': (-.03, -.02)}, sec_ci=(-.02, .01)))
    assert ok['variants']['P3-R']['rule_2'] and ok['main'] == 'P3-R'
    worse = phase3.decide(results(deltas={'P3-R': (-.06, -.02)}))
    assert not worse['variants']['P3-R']['rule_2'] and worse['main'] == 'M3'
    below = phase3.decide(results(deltas={'P3-R': (-.01, -.01)}, sec_ci=(-.05, -.01)))
    assert not below['variants']['P3-R']['rule_2']


def test_eta2_bounds():
    plies = np.arange(100, dtype=float)
    assert phase3.eta2(plies, plies) == pytest.approx(.99, abs=.01)
    assert phase3.eta2(np.ones(100), plies) is None
