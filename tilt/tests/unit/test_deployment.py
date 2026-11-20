import json

import joblib
import numpy as np
import pandas as pd
import pytest

from tilt.core import deployment, score
from tilt.core.train import calibrate, calibrated, predict_bundle
from tilt.evaluation import phase3, phase5
from tilt.evaluation.evaluate import contributions

from test_phase5 import frame


def install(tmp_path, features=None):
    f = frame()
    y = f.weak_tilt_label.to_numpy(dtype=float)
    train = np.flatnonzero((f.split == 'train').to_numpy() & np.isfinite(y))
    fitted = phase5.Fitted(phase3.VARIANTS['P3-B'], True, phase3.NO_INDICATOR).fit(f, y, train)
    calibration = calibrate(fitted.predict(f)[train], y[train].astype(int))
    bundle = dict(variant='P3-B', split='by_player', features=fitted.features, columns=fitted.columns,
                  imputer=fitted.imputer, keep=fitted.keep, scaler=fitted.scaler, classifier=fitted.model,
                  calibration=calibration, threshold=.3, threshold_source='test')
    folder = tmp_path / 'processed/models/phase5'
    folder.mkdir(parents=True)
    joblib.dump(bundle, folder / 'b.joblib')
    spec = dict(variant='P3-B', bundle='phase5/b.joblib', bundle_sha256=deployment.sha256_file(folder / 'b.joblib'),
                features=features or fitted.features)
    (tmp_path / deployment.DEPLOYED).write_text(json.dumps(spec))
    return f, fitted, calibration


def test_nothing_deployed(tmp_path):
    assert deployment.load(tmp_path) is None


def test_deployed_bundle_predicts_like_phase5(tmp_path):
    f, fitted, calibration = install(tmp_path)
    name, bundle = deployment.load(tmp_path)
    cal, regression, raw = predict_bundle(bundle, f)
    assert name == 'P3-B'
    assert np.allclose(raw, fitted.predict(f))
    assert np.allclose(cal, calibrated(calibration, fitted.predict(f)))
    assert np.isnan(regression).all()
    top = contributions(bundle, f.head(3))
    assert len(top) == 3 and all(len(t) == 3 for t in top)


def test_changed_bundle_or_features_are_refused(tmp_path):
    install(tmp_path)
    (tmp_path / 'processed/models/phase5/b.joblib').write_bytes(b'changed')
    with pytest.raises(ValueError, match='differs'):
        deployment.load(tmp_path)


def test_feature_list_must_match(tmp_path):
    install(tmp_path, features=['risk_rate'])
    with pytest.raises(ValueError, match='does not match'):
        deployment.load(tmp_path)


def test_prefix_dynamics_use_only_the_prefix():
    rng = np.random.default_rng(1)
    moves = pd.DataFrame(dict(player='p', game_id='g', ply=np.arange(1, 81, 2),
                              **{f: rng.integers(0, 2, 40).astype(float) for f in score.FLAGS}))
    whole = score.dynamics(moves).iloc[0]
    prefix = score.dynamics(moves[moves.ply <= 41]).iloc[0]
    assert set(score.DYNAMICS) <= set(whole.index)
    assert prefix.attack_trend_3w == pytest.approx(
        np.mean(np.array_split(moves.attack[:21].to_numpy(), 3)[2]) -
        np.mean(np.array_split(moves.attack[:21].to_numpy(), 3)[0]))
