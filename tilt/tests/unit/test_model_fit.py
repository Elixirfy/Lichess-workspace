import copy

import numpy as np
import pandas as pd

from tilt.evaluation import eval_metrics, p3b_features, model_fit

COLUMNS = sorted({c for f, _, _ in model_fit.XGB.values() for c in f} | {'losing_streak_before'})


def frame(n=300, seed=0):
    rng = np.random.default_rng(seed)
    data = {c: rng.normal(size=n) for c in COLUMNS}
    data['risk_rate'][:7] = np.nan            # keeps its missing indicator
    data['attack_trend_3w'][:9] = np.nan      # group B: no indicator
    data['lf_input__plies'] = rng.integers(10, 120, n).astype(float)
    signal = data['attack_rate'] + .5 * rng.normal(size=n)
    data['weak_tilt_label'] = np.where(rng.random(n) < .3, np.nan, (signal > .8).astype(float))
    data['result_score'] = rng.choice([0, .5, 1], n)
    data['rating'] = rng.integers(800, 2400, n).astype(float)
    data['player_id'] = [f'p{i % 30}' for i in range(n)]
    data['game_id'] = [f'g{i}' for i in range(n)]
    data['split'] = np.array(['train', 'validation', 'test'])[np.arange(n) % 30 // 10]
    return pd.DataFrame(data)


def test_fitted_reproduces_phase3_and_phase1_models():
    f = frame()
    y = f.weak_tilt_label.to_numpy(dtype=float)
    train = np.flatnonzero((f.split == 'train').to_numpy() & np.isfinite(y))
    cols = p3b_features.VARIANTS['P3-B']
    ours = model_fit.Fitted(cols, True, p3b_features.NO_INDICATOR).fit(f, y, train).predict(f)
    assert np.allclose(ours, p3b_features.fit_predict(cols, f, y, train))
    e0 = model_fit.Fitted(eval_metrics.E0, True, set()).fit(f, y, train).predict(f)
    assert np.allclose(e0, eval_metrics.fit_predict(eval_metrics.VARIANTS['E0'], f, y, train))
    length = model_fit.Fitted(['lf_input__plies'], False).fit(f, y, train).predict(f)
    assert np.allclose(length, eval_metrics.fit_predict(eval_metrics.BASELINES['B-length'], f, y, train))


def test_feature_lists_are_the_preregistered_ones():
    for c in model_fit.CANDIDATES:
        assert model_fit.XGB[c][0] == model_fit.PREREGISTERED[c]
        assert model_fit.XGB[model_fit.NOMETA[c]][0] == [x for x in model_fit.PREREGISTERED[c] if x not in model_fit.META]
        assert not [x for x in model_fit.XGB[c][0] if model_fit.banned(x)]
    assert model_fit.banned('lf_input__plies') and model_fit.banned(eval_metrics.MIDDLEGAME) and model_fit.banned('attack_rate_p40')


def test_bootstrap_excess_and_paired_differences():
    y = np.array([0, 1] * 20)
    players = np.repeat(np.arange(10), 4)
    long = np.ones(40, bool)
    boot = model_fit.bootstrap(players, y, dict(a=y.astype(float), b=y.astype(float)), long, (('a', 'b'),),
                            excess=('a',), repetitions=30)
    assert boot['paired']['primary']['a-b']['mean'] == 0
    assert np.isclose(boot['excess_ge40']['a']['mean'], .5)


def test_permutation_importance_finds_the_signal():
    f = frame()
    y = f.weak_tilt_label.to_numpy(dtype=float)
    train = np.flatnonzero((f.split == 'train').to_numpy() & np.isfinite(y))
    val = np.flatnonzero((f.split == 'validation').to_numpy() & np.isfinite(y))
    model = model_fit.Fitted(p3b_features.VARIANTS['M3'], True, p3b_features.NO_INDICATOR).fit(f, y, train)
    importance = model_fit.permutation_importance(model, f, val, y[val].astype(int), repeats=5)
    assert next(iter(importance)) == 'attack_rate'


def fake(nometa_ratio=.9, ece=.03, p3b=.5, m3=.45):
    def split():
        models = {n: dict(primary=dict(pr_auc=.2), excess_ge40=.05, calibrated=dict(brier_skill=.1, ece=ece))
                  for n in model_fit.MODELS}
        for name, value in (('P3-B', p3b), ('M3', m3)):
            models[name]['primary']['pr_auc'] = value
            models[model_fit.NOMETA[name]]['primary']['pr_auc'] = value * nometa_ratio
        boot = dict(excess_ge40={c: dict(ci=[.01, .1]) for c in model_fit.CANDIDATES},
                    paired=dict(primary={f'{a}-{b}': dict(ci=[.05, .3]) for a, b in model_fit.PAIRS}))
        ranking = {c: dict.fromkeys(model_fit.XGB[c][0], 0.) for c in model_fit.CANDIDATES}
        return dict(validation=dict(importance=ranking), test=dict(models=models, bootstrap=boot, importance=ranking))
    return {s: split() for s in model_fit.SPLITS}


REGISTERED = set(model_fit.PREREGISTERED['P3-B'])


def test_decision_rules():
    good = model_fit.decide(fake(), REGISTERED)
    assert (good['provisional_choice'], good['rule']) == ('P3-B', 1)
    worse = model_fit.decide(fake(p3b=.4), REGISTERED)        # P3-B passes gates but is below M3 on test
    assert (worse['provisional_choice'], worse['rule']) == ('M3', 2)
    meta = model_fit.decide(fake(nometa_ratio=.5), REGISTERED)  # both depend on metadata
    assert (meta['provisional_choice'], meta['rule']) == (None, 3)
    assert not meta['gates']['P3-B']['5']['passed']
    hot = model_fit.decide(fake(ece=.06), REGISTERED)          # ECE above the A limit fails gate 6
    assert hot['provisional_choice'] is None
    unregistered = model_fit.decide(fake(), REGISTERED - {'behavior_change_point'})
    assert unregistered['provisional_choice'] == 'M3'
    assert unregistered['gates']['P3-B']['8']['passed'] is None


def test_differences_ignore_elapsed_and_catch_drift():
    a = dict(x=1.0, elapsed_seconds=3, y=[1, 'a'])
    b = copy.deepcopy(a) | dict(elapsed_seconds=9)
    assert model_fit.differences(a, b) == dict(max_abs=0., mismatches=[])
    b['x'] = 1.00001
    assert model_fit.differences(a, b)['max_abs'] > model_fit.REPRODUCIBLE
    b['y'][1] = 'b'
    assert model_fit.differences(a, b)['mismatches']


def test_validation_stage_never_reads_test_labels():
    f = frame()
    flipped = f.copy()
    test = flipped.split.eq('test') & flipped.weak_tilt_label.notna()
    flipped.loc[test, 'weak_tilt_label'] = 1 - flipped.loc[test, 'weak_tilt_label']
    _, one = model_fit.validation_stage(f, repetitions=10)
    _, two = model_fit.validation_stage(flipped, repetitions=10)
    assert model_fit.differences(one, two) == dict(max_abs=0., mismatches=[])
