"""Live M-v3 scoring for the lila worker (reports/label_v3_deployment.md, I0).

The frozen S3/S4 code computes every model input, score and rule outcome. This module
only builds one player's headers from a worker data root, picks the head, and explains
the score. Scores predict the v3 behaviour rule early; they do not measure emotion.

`processed/models/deployed_v3.json` switches the worker to M-v3. Deleting it restores
the P3-B path (`deployment.py`), which is left unchanged.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import shutil

import joblib
import numpy as np
import pandas as pd

from ..core.train import numeric
from ..data import cohort_v3
from ..evaluation import v3_p3b, v3_train as train
from ..features import prefix_v3 as prefix
from ..labels import rules_v3 as rules, split_v3 as split

POINTER = Path('processed/models/deployed_v3.json')
MODEL = 'M-v3'
BUNDLE_SHA = '9ebc9730c6e00ee26c51f012259c02f10eb276501744fe1d8137c3b6855baae5'
# I0 section 1: the deployed path runs these files byte for byte.
FROZEN = {
    prefix: '71b92e6e8ca3bde07508cc29a88aa1563e8ece7af1a640de4f3e5a4536b53f3d',
    rules: '9f2d8234377999965699be45aa466595447fad3dcf93709cf7ff89ed5a2a0a8a',
    split: 'f426e79254167d3f998f1b075f720b3b89098d52b37930f4bf975bd3fb6fa4ff',
    cohort_v3: '08f33a448fdf199556fc879491eb4b9f3b9d3f6e4ed938c105d3e5c5dbd2dc9d',
    train: 'ee8c3ca08f154d350da46c297677b0b898f9983b71ce1d879a4f7da53eae99b5',
    v3_p3b: '1fa43330c85884b3bdeab3ae6645a4beb9b46098962f51d1110fa1ebf3bffa0e',
}
BANDS = dict(attention=.10, high=.30)
SPEED = 'blitz'
COHORT = 'live'
HIDDEN = ('meta', 'skill')  # never shown as a reason; they still count in the score
SIGN_SHARE = .10
SIGN_MAX = 3
FAST_Z, FAST_TRIM, FAST_GAMES, FAST_DROP = -1.5, -1.0, 20, 4
HEADER_COLS = list(dict.fromkeys(['player', 'game_id', 'color', 'session_id', 'start_ms', 'end_ms',
    'end_upper_ms', 'rating', 'opponent_rating', 'result_score', 'speed', *prefix.HISTORY]))
CONTEXT = tuple(f'C{i}' for i in range(1, 6))


def sha256_file(path):
    return split.sha(path)


class Deployed:
    def __init__(self, spec, bundle, registry, pointer):
        self.spec, self.bundle, self.registry, self.pointer = spec, bundle, registry, pointer
        self.family = dict(zip(registry.column, registry.family))
        self.skill = set(train.skill_columns(registry))
        self.bands = dict(spec['bands'])

    def shadow_on(self, today=None):
        until = self.spec.get('shadow_until')
        if not until:
            return False
        today = today or datetime.datetime.now(datetime.UTC).date()
        return today <= datetime.date.fromisoformat(until)


def check_frozen():
    for module, expected in FROZEN.items():
        if sha256_file(module.__file__) != expected:
            raise ValueError(f'Frozen v3 code changed: {Path(module.__file__).name}')


def load(models, pointer=None):
    """The deployed M-v3, or None when deployed_v3.json is absent."""
    path = Path(pointer) if pointer else Path(models) / POINTER
    if not path.exists():
        return None
    spec = json.loads(path.read_text())
    check_frozen()
    if spec.get('model') != MODEL or spec.get('bundle_sha256') != BUNDLE_SHA:
        raise ValueError('deployed_v3.json does not name the adopted M-v3 bundle')
    bundle_path, registry_path = path.parent / spec['bundle'], path.parent / spec['registry']
    if sha256_file(bundle_path) != BUNDLE_SHA:
        raise ValueError('Deployed M-v3 bundle differs from deployed_v3.json; restore it or remove deployed_v3.json')
    if sha256_file(registry_path) != spec['registry_sha256']:
        raise ValueError('Deployed v3 registry differs from deployed_v3.json')
    if dict(spec['bands']) != BANDS:
        raise ValueError('Level bands differ from I0 section 4')
    manifest = Path(models) / 'processed/features/manifest.json'
    if sha256_file(manifest) != split.MANIFEST_SHA:
        raise ValueError('Feature settings differ from the trained data')
    return validated(spec, joblib.load(bundle_path), pd.read_csv(registry_path), path)


def validated(spec, bundle, registry, path=None):
    pd.testing.assert_frame_equal(registry.reset_index(drop=True), prefix.registry(()), check_dtype=False)
    if bundle.get('candidate') != MODEL or set(bundle.get('heads', {})) != {'pre', 'p20'}:
        raise ValueError('Bundle is not the two-head M-v3')
    for head, block in (('pre', ['pre']), ('p20', ['pre', 'p20'])):
        expected = registry.loc[registry.block.isin(block), 'column'].tolist()
        if list(bundle['heads'][head]['features']) != expected:
            raise ValueError('M-v3 head inputs differ from the registry')
    return Deployed(spec, bundle, registry, path)


def headers(root, player):
    """One player's blitz headers, with the columns split_v3.load_headers produces."""
    root = Path(root)
    games = pd.read_parquet(root / 'features/games.parquet', columns=HEADER_COLS)
    games = games[games.player.str.lower().eq(player.lower()) & games.speed.eq(SPEED)].copy()
    if games.empty:
        raise ValueError('No local feature rows for this player')
    if games.duplicated(['game_id', 'color']).any():
        raise ValueError('Duplicate player sides')
    raw = split.raw_games(root)
    raw = raw[raw.game_id.isin(games.game_id)].rename(columns={'game_id': 'raw_game_id'})
    games = games.rename(columns={'game_id': 'raw_game_id'}).merge(raw, on='raw_game_id', how='left',
                                                                   validate='many_to_one')
    if games[['start_ms', 'session_id', 'plies']].isna().any().any():
        raise ValueError('Incomplete required headers')
    if not games.rating.eq(games.white_rating.where(games.color.eq('white'), games.black_rating)).all():
        raise ValueError('Pre-game rating mismatch')
    games['game_id'] = games.raw_game_id
    games['player_id'] = player.lower()
    games['cohort'] = COHORT
    # Plain history/target rows, as the S5 adapter passes them to the frozen builder.
    games['assignment'] = 'development'
    games['part'] = 'train'
    return games.sort_values(['start_ms', 'game_id']).reset_index(drop=True)


def player_moves(root, games):
    moves = pd.read_parquet(Path(root) / 'features/moves.parquet', columns=prefix.MOVE_COLS,
                            filters=[('game_id', 'in', games.raw_game_id.unique().tolist())])
    if moves.duplicated(['game_id', 'ply']).any():
        raise ValueError('Duplicate physical plies')
    return moves


def level(prob, bands=BANDS):
    return 'high' if prob >= bands['high'] else 'attention' if prob >= bands['attention'] else 'low'


def head_matrix(model, head, pre, p20):
    frame = pre if head == 'pre' else pre.merge(p20, on=prefix.IDS + ['part'], validate='one_to_one')
    x = train.matrix(frame, head, MODEL, model.registry)
    if list(x) != list(model.bundle['heads'][head]['features']):
        raise ValueError('Frozen matrix column order')
    return x


def scores(model, pre, p20, plies):
    """Frozen all-validation Platt scores of both heads and the S4 composite."""
    out = {}
    for head in ('pre', 'p20'):
        vector = np.full(len(pre), np.nan)
        if head == 'pre' or len(p20):
            rows = np.arange(len(pre)) if head == 'pre' else np.flatnonzero(np.asarray(plies) >= 20)
            x = head_matrix(model, head, pre.iloc[rows] if head == 'p20' else pre, p20)
            if len(x) != len(rows):
                raise ValueError('Head rows differ from the P-20 population')
            if len(x):
                vector[rows] = train.predict_bundle(model.bundle['heads'][head], x)[0]
        out[head] = vector
    out['composite'] = train.composite(plies, out['pre'], out['p20'])
    return out


def contributions(model, head, x):
    """XGBoost margin contributions (SHAP) of one row, per input column."""
    import xgboost
    b = model.bundle['heads'][head]
    values = b['scaler'].transform(b['imputer'].transform(numeric(x, b['features']))[:, b['keep']]).astype(np.float32)
    contrib = b['classifier'].get_booster().predict(xgboost.DMatrix(values), pred_contribs=True)[0]
    raw = float(b['classifier'].predict_proba(values)[:, 1][0])
    margin = float(np.log(raw / (1 - raw))) if 0 < raw < 1 else None
    if margin is not None and abs(float(contrib.sum()) - margin) > 1e-3:
        raise ValueError('SHAP contributions do not sum to the model margin')
    return dict(zip(b['columns'], contrib[:-1].astype(float)))


def signs(model, head, x):
    """I0 section 5: families with >= 10% of the positive push; meta and skill hidden."""
    sums = {}
    for column, value in contributions(model, head, x).items():
        feature = column.removesuffix('__missing')
        family = 'skill' if feature in model.skill else model.family[feature]
        sums[family] = sums.get(family, 0.) + value
    positive = {f: v for f, v in sums.items() if v > 0}
    total = sum(positive.values())
    if total <= 0:
        return []
    shown = [(f, v / total) for f, v in positive.items() if f not in HIDDEN and v / total >= SIGN_SHARE]
    shown.sort(key=lambda kv: (-kv[1], kv[0]))
    return [dict(family=f, share=round(float(s), 3)) for f, s in shown[:SIGN_MAX]]


def trimmed_think(game, moves, drop=FAST_DROP):
    m = moves[moves.game_id.eq(game['raw_game_id']) & moves.ply.between(1, 20)].sort_values('ply')
    own = m[m.color.eq(game['color'])].iloc[drop:]
    thinks = own.think_seconds.dropna().to_numpy(dtype=float)
    budget = game['initial_seconds'] + 40 * game['increment_seconds']
    return float(np.median(thinks) / budget) if len(thinks) >= 5 and budget > 0 else np.nan


def robust_z(value, values, floor):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 5 or not np.isfinite(value):
        return np.nan
    median = np.median(values)
    return float((value - median) / max(1.4826 * np.median(np.abs(values - median)), floor))


def fast(games, moves, target, z_model):
    """I0 section 6. Only hides the reason; never changes the score."""
    if not np.isfinite(z_model) or z_model > FAST_Z:
        return None
    g, _ = prefix.aggregate_player(games, moves)
    eligible = g[g.start_ms.le(target['start_ms']) & g.plies.ge(20)]
    complete = {(x['game_id'], x['color']) for x in eligible.to_dict('records')
                if prefix.prefix_status(x, moves) == 'complete'}
    row = g[g.game_id.eq(target['game_id']) & g.color.eq(target['color'])].iloc[0].to_dict()
    window = prefix.prefix_reference(row, g, complete).to_dict('records')
    floor = prefix.FLOORS['think_frac_median']
    original = [prefix.prefix_stats(x, moves)['think_frac_median'] for x in window]
    current = prefix.prefix_stats(row, moves)['think_frac_median']
    # The shown number must be the model input itself.
    if not np.isclose(robust_z(current, original, floor), z_model, rtol=0, atol=1e-12):
        raise ValueError('Fast-reason z differs from the model input')
    games_used = int(np.isfinite(np.asarray(original, dtype=float)).sum())
    if games_used < FAST_GAMES:
        return None
    z_trim = robust_z(trimmed_think(row, moves), [trimmed_think(x, moves) for x in window], floor)
    if not np.isfinite(z_trim) or z_trim > FAST_TRIM:
        return None
    return dict(z=round(float(z_model), 1), zTrim=round(float(z_trim), 1), games=games_used)


def rule_check(label, later_game):
    """I0 section 7, from the frozen rules_v3 row of this game."""
    pending = []
    if (label['E7'] == 'missing' and label['result_score'] == 0 and not later_game
            and pd.notna(label['gap_q20_seconds'])):
        pending = ['E7']
    fired = [c for c in CONTEXT if bool(label[c])] + [e for e in rules.EVIDENCE if label[e] == 'fired']
    missing = [e for e in rules.EVIDENCE if label[e] == 'missing' and e not in pending]
    return dict(label=str(label['label']), context=str(label['level']), fired=fired, missing=missing,
                pending=pending, reason=str(label['abstain_reason']) or None)


def target_rows(games, game_id):
    target = games[games.raw_game_id.eq(game_id)]
    if target.empty:
        raise ValueError('No matching local game for this player')
    return target


def rules_for(games, moves, target):
    labels = prefix.build_player(games, moves, target, 'labels', ())
    later = bool(games.start_ms.gt(target.start_ms.iloc[0]).any())
    return rule_check(labels.iloc[0].to_dict(), later)


def assess(model, root, player, game_id):
    """Response fields for one queued game: {'pred': ...} or {'skip': ...}."""
    return evaluate(model, root, player, game_id)[0]


def evaluate(model, root, player, game_id):
    """(response fields, unrounded composite probability or None)."""
    games = headers(root, player)
    target = target_rows(games, game_id)
    if target.speed.iloc[0] != SPEED:
        return dict(skip='speed'), None
    moves = player_moves(root, games)
    pre, p20 = prefix.build_player(games, moves, target, 'features', ())
    if pre.empty:
        return dict(skip='incomplete'), None  # E4 one-colour prefix, the S3-S5 exclusion
    plies = int(target.plies.iloc[0])
    head = 'p20' if plies >= 20 else 'pre'
    prob = float(scores(model, pre, p20, [plies])['composite'][0])
    x = head_matrix(model, head, pre, p20)
    found = signs(model, head, x)
    pred = dict(score=int(round(100 * prob)), flag=bool(prob >= model.bands['high']),
                factors=[s['family'] for s in found], v=3, prob=round(prob, 4),
                level=level(prob, model.bands), head=head, signs=found,
                rules=rules_for(games, moves, target))
    if head == 'p20':
        reason = fast(games, moves, target.iloc[0].to_dict(), float(p20['p20_z_think_frac_median'].iloc[0]))
        if reason:
            pred['fast'] = reason
    return dict(pred=pred), prob


def refresh_rules(root, player, game_id):
    """Recompute a scored game's rule check once later games exist (E7)."""
    games = headers(root, player)
    target = target_rows(games, game_id)
    return rules_for(games, player_moves(root, games), target)


def install(models, bundle, registry, shadow_days=14, today=None):
    """The I0 switch: copy the frozen files into the models root and write the pointer."""
    models = Path(models)
    folder = models / 'processed/models/v3'
    path = models / POINTER
    if path.exists():
        raise FileExistsError('deployed_v3.json already exists')
    if sha256_file(bundle) != BUNDLE_SHA:
        raise ValueError('Not the adopted M-v3 bundle')
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(bundle, folder / 'M-v3.joblib')
    shutil.copyfile(registry, folder / 'feature_registry.csv')
    today = today or datetime.datetime.now(datetime.UTC).date()
    spec = dict(model=MODEL, bundle='v3/M-v3.joblib', bundle_sha256=BUNDLE_SHA,
                registry='v3/feature_registry.csv', registry_sha256=sha256_file(folder / 'feature_registry.csv'),
                bands=BANDS, source='label v3 S4 run1 bundle; adopted in principle by S5',
                spec='reports/label_v3_deployment.md', deployed_on=today.isoformat(),
                shadow_until=(today + datetime.timedelta(days=shadow_days)).isoformat())
    path.write_text(json.dumps(spec, indent=2) + '\n')
    load(models)  # refuse a broken install immediately
    return spec


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='step', required=True)
    p = sub.add_parser('install', help='I0 switch: write deployed_v3.json')
    p.add_argument('--models', type=Path, required=True)
    p.add_argument('--bundle', type=Path, required=True)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--shadow-days', type=int, default=14)
    s = sub.add_parser('score', help='Score one local game (prints the response fields)')
    s.add_argument('--models', type=Path, required=True)
    s.add_argument('--root', type=Path, required=True, help='Worker data root/processed')
    s.add_argument('--player', required=True)
    s.add_argument('--game', required=True)
    args = parser.parse_args(argv)
    if args.step == 'install':
        print(json.dumps(install(args.models, args.bundle, args.registry, args.shadow_days), indent=2))
    else:
        model = load(args.models)
        if model is None:
            raise SystemExit('deployed_v3.json is absent')
        print(json.dumps(assess(model, args.root, args.player, args.game), indent=2))


if __name__ == '__main__':
    main()
