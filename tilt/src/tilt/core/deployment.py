"""The deployed Phase 5 model (reports/final_model_comparison.md).

`processed/models/deployed.json` names a frozen Phase 5 bundle and its sha256. When the file exists, `score.run`
uses that bundle instead of `selection.json`; deleting the file restores the previous model.
"""
import hashlib
import json
from pathlib import Path

import joblib

from ..evaluation.phase5 import banned
from ..features.model_features import assert_no_lf_inputs

DEPLOYED = Path('processed/models/deployed.json')


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(models):
    """(variant name, bundle) of the deployed Phase 5 model, or None when nothing is deployed."""
    path = Path(models) / DEPLOYED
    if not path.exists():
        return None
    spec = json.loads(path.read_text())
    bundle_path = path.parent / spec['bundle']
    if sha256_file(bundle_path) != spec['bundle_sha256']:
        raise ValueError('Deployed bundle differs from deployed.json; restore it or remove deployed.json')
    bundle = joblib.load(bundle_path)
    if bundle['variant'] != spec['variant'] or list(bundle['features']) != list(spec['features']):
        raise ValueError('Deployed bundle does not match deployed.json')
    bad = [f for f in bundle['features'] if banned(f)]
    if bad:
        raise ValueError('Deployed model uses banned inputs: ' + ', '.join(bad))
    assert_no_lf_inputs(bundle['features'])
    # Reference values for score.contributions: the train medians the imputer fills in.
    bundle['reference'] = list(bundle['imputer'].statistics_[:len(bundle['features'])])
    bundle['format'] = 'phase5'
    bundle['model'] = 'xgboost'
    return spec['variant'], bundle
