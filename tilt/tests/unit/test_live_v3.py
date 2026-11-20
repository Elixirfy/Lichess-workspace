"""Live M-v3 path (reports/label_v3_deployment.md) on synthetic roots; no real data or bundle."""
import datetime
import json
import sqlite3

import joblib
import numpy as np
import pandas as pd
import pytest

from tilt.core import live_v3 as live
from tilt.evaluation import v3_train as train
from tilt.features import prefix_v3 as prefix
from test_prefix_v3 import fixture
from test_v3_holdout import bundle as fake_head

PLAYER = 'synthetic'


def gid(i):
    return f'fixture-game-{i:03}'


def write_root(root, games, moves):
    (root / 'features').mkdir(parents=True, exist_ok=True)
    (root / 'normalized/games').mkdir(parents=True, exist_ok=True)
    g = games.copy()
    g['white_rating'] = g.rating.where(g.color.eq('white'), g.opponent_rating)
    g['black_rating'] = g.opponent_rating.where(g.color.eq('white'), g.rating)
    g['rated'] = True
    g[live.HEADER_COLS].to_parquet(root / 'features/games.parquet')
    g[['game_id', 'status', 'plies', 'rated', 'initial_seconds', 'increment_seconds', 'white_rating',
       'black_rating']].drop_duplicates('game_id').to_parquet(root / 'normalized/games/b1.parquet')
    with sqlite3.connect(root / 'index.sqlite') as db:
        db.execute('CREATE TABLE IF NOT EXISTS batches (batch TEXT)')
        db.execute('DELETE FROM batches')
        db.execute("INSERT INTO batches VALUES ('b1')")
    moves[prefix.MOVE_COLS].to_parquet(root / 'features/moves.parquet')
    return root


def heads(registry=None):
    registry = prefix.registry(()) if registry is None else registry
    return {h: fake_head(registry.loc[registry.block.isin(b), 'column'].tolist())
            for h, b in (('pre', ['pre']), ('p20', ['pre', 'p20']))}


def model():
    registry = prefix.registry(())
    return live.validated(dict(bands=live.BANDS), dict(candidate='M-v3', heads=heads(registry)), registry)


@pytest.fixture
def no_shap(monkeypatch):
    # The fake heads have no booster; signs are tested on their own below.
    monkeypatch.setattr(live, 'contributions', lambda m, head, x: {})


def quick(moves, i):
    """Make the player's own moves in game i much faster than usual."""
    mask = moves.game_id.eq(gid(i)) & moves.color.eq('white')
    moves.loc[mask, 'think_seconds'] = 0.2
    return moves


def test_blitz_game_scored_with_full_response(tmp_path, no_shap):
    games, moves = fixture(n=30)
    root = write_root(tmp_path, games, quick(moves, 29))
    m = model()
    response, prob = live.evaluate(m, root, PLAYER.upper(), gid(29))
    pred = response['pred']
    assert set(pred) == {'score', 'flag', 'factors', 'v', 'prob', 'level', 'head', 'signs', 'rules', 'fast'}
    assert pred['v'] == 3 and pred['head'] == 'p20' and pred['score'] == int(round(100 * prob))
    assert pred['prob'] == round(prob, 4) and pred['level'] == live.level(prob)
    assert pred['flag'] == (prob >= live.BANDS['high'])
    assert set(pred['rules']) == {'label', 'context', 'fired', 'missing', 'pending', 'reason'}
    assert set(pred['fast']) == {'z', 'zTrim', 'games'} and pred['fast']['games'] >= live.FAST_GAMES
    assert pred['fast']['z'] <= live.FAST_Z and pred['fast']['zTrim'] <= live.FAST_TRIM
    json.dumps(response)  # BSON/JSON-safe plain types
    # The per-game path equals the frozen batch composite.
    g = live.headers(root, PLAYER)
    mv = live.player_moves(root, g)
    pre, p20 = prefix.build_player(g, mv, g.iloc[[29]], 'features', ())
    assert prob == live.scores(m, pre, p20, [40])['composite'][0]
    assert live.assess(m, root, PLAYER, gid(29)) == response


def test_levels_and_bands():
    assert [live.level(p) for p in (0, .0999, .10, .2999, .30, 1)] == \
        ['low', 'low', 'attention', 'attention', 'high', 'high']


def test_short_game_uses_pre_head_without_fast(tmp_path, no_shap):
    games, moves = fixture(n=30)
    games.loc[29, 'plies'] = 15
    moves = quick(moves, 29)
    moves = moves[~(moves.game_id.eq(gid(29)) & moves.ply.gt(15))]
    root = write_root(tmp_path, games, moves)
    pred = live.assess(model(), root, PLAYER, gid(29))['pred']
    assert pred['head'] == 'pre' and 'fast' not in pred


def test_other_speeds_are_neither_target_nor_history(tmp_path, no_shap):
    games, moves = fixture(n=30)
    m = model()
    blitz_only = live.evaluate(m, write_root(tmp_path / 'a', games.drop([5, 6]), moves), PLAYER, gid(29))
    games.loc[[5, 6], 'speed'] = 'bullet'
    root = write_root(tmp_path / 'b', games, moves)
    assert len(live.headers(root, PLAYER)) == 28
    assert live.evaluate(m, root, PLAYER, gid(29)) == blitz_only
    with pytest.raises(ValueError, match='^No matching local game'):
        live.assess(m, root, PLAYER, gid(5))
    with pytest.raises(ValueError, match='^No local feature rows'):
        live.assess(m, root, 'someone-else', gid(29))


def test_one_colour_prefix_is_skipped(tmp_path, no_shap):
    games, moves = fixture(n=30)
    # A guest opponent: compute() leaves only the player's own moves.
    moves = moves[~(moves.game_id.eq(gid(29)) & moves.color.eq('black'))]
    root = write_root(tmp_path, games, moves)
    assert live.evaluate(model(), root, PLAYER, gid(29)) == (dict(skip='incomplete'), None)


def test_null_result_is_scored(tmp_path, no_shap):
    games, moves = fixture(n=30)
    games.loc[29, 'result_score'] = np.nan
    root = write_root(tmp_path, games, moves)
    response, prob = live.evaluate(model(), root, PLAYER, gid(29))
    assert np.isfinite(prob) and 'E7' not in response['pred']['rules']['pending']


def test_e7_pending_until_the_next_game(tmp_path, no_shap):
    games, moves = fixture(n=30)
    assert games.result_score[28] == 0  # a loss: E7 can fire once the next game exists
    root = write_root(tmp_path, games.iloc[:29], moves[moves.game_id.ne(gid(29))])
    m = model()
    before = live.assess(m, root, PLAYER, gid(28))['pred']['rules']
    assert before['pending'] == ['E7'] and 'E7' not in before['missing'] + before['fired']
    write_root(tmp_path, games, moves)
    after = live.refresh_rules(root, PLAYER, gid(28))
    assert after['pending'] == [] and 'E7' not in after['missing']
    full = live.assess(m, root, PLAYER, gid(28))['pred']['rules']
    assert after == full


def column(registry, family, block='pre', skip=()):
    rows = registry[registry.family.eq(family) & registry.block.eq(block) & ~registry.column.isin(skip)]
    return rows.column.iloc[0]


def test_signs_show_families_with_ten_percent_and_hide_meta_and_skill(monkeypatch):
    m = model()
    reg = m.registry
    skill = train.skill_columns(reg)
    values = {
        column(reg, 'session'): 3.0,
        column(reg, 'previous') + '__missing': 2.0,  # indicator counts for its feature's family
        column(reg, 'history'): 0.8,  # below 10% of the positive total
        column(reg, 'quality', 'p20'): 0.9,  # below 10% too
        column(reg, 'meta', skip=skill): 2.5,  # hidden but still in the total
        skill[0]: 0.6,  # skill pseudo-family, hidden
        column(reg, 'baseline', skip=skill): -4.0,  # negative pushes are never signs
    }
    monkeypatch.setattr(live, 'contributions', lambda model, head, x: values)
    total = 3 + 2 + .8 + .9 + 2.5 + .6
    assert live.signs(m, 'p20', None) == [dict(family='session', share=round(3 / total, 3)),
                                          dict(family='previous', share=round(2 / total, 3))]
    values[column(reg, 'history')] = 1.5
    assert [s['family'] for s in live.signs(m, 'p20', None)] == ['session', 'previous', 'history']
    values[column(reg, 'time', 'p20')] = 1.4
    shown = live.signs(m, 'p20', None)
    assert len(shown) == live.SIGN_MAX and shown[-1]['family'] == 'history'
    monkeypatch.setattr(live, 'contributions', lambda model, head, x: {column(reg, 'session'): -1.0})
    assert live.signs(m, 'pre', None) == []


def test_contributions_are_real_shap_values():
    from types import SimpleNamespace
    from sklearn.impute import SimpleImputer
    from sklearn.preprocessing import StandardScaler
    from xgboost import XGBClassifier
    rng = np.random.default_rng(3)
    x = pd.DataFrame(rng.normal(size=(200, 3)), columns=['a', 'b', 'c'])
    x.loc[::7, 'b'] = np.nan
    y = (x.a.fillna(0) + .5 * rng.normal(size=200) > 0).astype(int)
    imputer = SimpleImputer(strategy='median', add_indicator=True).fit(x.to_numpy())
    values = imputer.transform(x.to_numpy())
    scaler = StandardScaler().fit(values)
    clf = XGBClassifier(n_estimators=10, max_depth=2, random_state=0).fit(scaler.transform(values).astype(np.float32), y)
    head = dict(features=['a', 'b', 'c'], columns=['a', 'b', 'c', 'b__missing'], imputer=imputer,
                keep=np.arange(4), scaler=scaler, classifier=clf)
    out = live.contributions(SimpleNamespace(bundle=dict(heads=dict(pre=head))), 'pre', x.iloc[[7]])
    assert list(out) == ['a', 'b', 'c', 'b__missing'] and all(isinstance(v, float) for v in out.values())


def test_fast_reason_gates(tmp_path, no_shap):
    games, moves = fixture(n=30)
    root = write_root(tmp_path, games, quick(moves, 29))
    g = live.headers(root, PLAYER)
    mv = live.player_moves(root, g)
    target = g.iloc[29].to_dict()
    _, p20 = prefix.build_player(g, mv, g.iloc[[29]], 'features', ())
    z = float(p20['p20_z_think_frac_median'].iloc[0])
    assert z <= live.FAST_Z and live.fast(g, mv, target, z) is not None
    assert live.fast(g, mv, target, -1.4) is None and live.fast(g, mv, target, np.nan) is None
    with pytest.raises(ValueError, match='model input'):
        live.fast(g, mv, target, z - 1)
    # Fewer than 20 usable reference games: the reason stays hidden.
    short = g[g.start_ms.ge(g.start_ms.iloc[12])].reset_index(drop=True)
    target = short.iloc[-1].to_dict()
    _, p20 = prefix.build_player(short, mv, short.iloc[[-1]], 'features', ())
    z = float(p20['p20_z_think_frac_median'].iloc[0])
    assert z <= live.FAST_Z and live.fast(short, mv, target, z) is None


def test_fast_reason_needs_the_trimmed_median_too(tmp_path, no_shap):
    games, moves = fixture(n=30)
    own = moves.game_id.eq(gid(29)) & moves.color.eq('white')
    # Six quick opening moves set the median; after the first four the player thinks long.
    moves.loc[own & moves.ply.le(11), 'think_seconds'] = 0.2
    moves.loc[own & moves.ply.between(13, 20), 'think_seconds'] = 8.0
    root = write_root(tmp_path, games, moves)
    g = live.headers(root, PLAYER)
    mv = live.player_moves(root, g)
    _, p20 = prefix.build_player(g, mv, g.iloc[[29]], 'features', ())
    z = float(p20['p20_z_think_frac_median'].iloc[0])
    assert z <= live.FAST_Z
    assert live.fast(g, mv, g.iloc[29].to_dict(), z) is None


def test_trimmed_think_drops_the_first_four_own_moves():
    game = dict(raw_game_id='x', color='white', initial_seconds=180., increment_seconds=2.)
    moves = pd.DataFrame(dict(game_id='x', ply=range(1, 21), color=['white', 'black'] * 10,
                              think_seconds=[100.] * 8 + [1., 2., 3., 4., 5., 6., 7., 8., 9., 10., 11., 12.]))
    # Own plies 9..19 remain after dropping plies 1, 3, 5 and 7.
    assert live.trimmed_think(game, moves) == pytest.approx(np.median([1., 3., 5., 7., 9., 11.]) / 260)
    assert np.isnan(live.trimmed_think(game, moves[moves.ply.le(12)]))  # < 5 own thinks remain
    assert np.isnan(live.robust_z(1., [1., 2.], .1)) and live.robust_z(3., [1.] * 5, .5) == 4.


def test_rule_check_fields():
    label = dict(label='ABSTAIN', level='weak', abstain_reason='too_few', result_score=0., gap_q20_seconds=50.,
                 **{c: c in ('C2',) for c in live.CONTEXT},
                 **{e: 'fired' if e == 'E1' else 'missing' if e in ('E4', 'E7') else 'not_fired'
                    for e in live.rules.EVIDENCE})
    out = live.rule_check(label, later_game=False)
    assert out == dict(label='ABSTAIN', context='weak', fired=['C2', 'E1'], missing=['E4'], pending=['E7'],
                       reason='too_few')
    assert live.rule_check(label, later_game=True)['pending'] == []
    assert live.rule_check(dict(label, result_score=1.), False)['pending'] == []
    assert live.rule_check(dict(label, gap_q20_seconds=np.nan), False)['missing'] == ['E4', 'E7']


def manifest(models, monkeypatch):
    path = models / 'processed/features/manifest.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"window_plies": 12}\n')
    monkeypatch.setattr(live.split, 'MANIFEST_SHA', live.sha256_file(path))


def saved_bundle(tmp_path, monkeypatch):
    path = tmp_path / 'M-v3.joblib'
    joblib.dump(dict(candidate='M-v3', heads=heads()), path)
    registry = tmp_path / 'feature_registry.csv'
    prefix.registry(()).to_csv(registry, index=False)
    monkeypatch.setattr(live, 'BUNDLE_SHA', live.sha256_file(path))
    return path, registry


def test_install_load_and_rollback(tmp_path, monkeypatch):
    models = tmp_path / 'models'
    manifest(models, monkeypatch)
    assert live.load(models) is None  # no pointer: the P3-B path stays
    bundle, registry = saved_bundle(tmp_path, monkeypatch)
    spec = live.install(models, bundle, registry, today=datetime.date(2026, 11, 17))
    assert spec['shadow_until'] == '2026-12-01' and spec['bands'] == live.BANDS
    deployed = live.load(models)
    assert deployed.shadow_on(datetime.date(2026, 12, 1)) and not deployed.shadow_on(datetime.date(2026, 12, 2))
    with pytest.raises(FileExistsError):
        live.install(models, bundle, registry)
    (models / live.POINTER).unlink()
    assert live.load(models) is None


def test_load_refuses_changed_files(tmp_path, monkeypatch):
    models = tmp_path / 'models'
    manifest(models, monkeypatch)
    bundle, registry = saved_bundle(tmp_path, monkeypatch)
    live.install(models, bundle, registry)
    pointer = models / live.POINTER
    spec = json.loads(pointer.read_text())
    pointer.write_text(json.dumps(dict(spec, bands=dict(attention=.1, high=.25))))
    with pytest.raises(ValueError, match='bands'):
        live.load(models)
    pointer.write_text(json.dumps(spec))
    (models / 'processed/models/v3/M-v3.joblib').write_bytes(b'changed')
    with pytest.raises(ValueError, match='bundle differs'):
        live.load(models)
    with pytest.raises(ValueError, match='adopted'):
        live.install(tmp_path / 'other', tmp_path / 'feature_registry.csv', registry)


def test_validated_refuses_other_bundles():
    reg = prefix.registry(())
    with pytest.raises(ValueError):
        live.validated({}, dict(candidate='P3-B/v3', heads=heads(reg)), reg)
    h = heads(reg)
    h['pre'] = fake_head(list(reversed(h['pre']['features'])))
    with pytest.raises(ValueError):
        live.validated({}, dict(candidate='M-v3', heads=h), reg)


def test_frozen_code_is_checked(monkeypatch):
    live.check_frozen()
    monkeypatch.setitem(live.FROZEN, live.rules, '0' * 64)
    with pytest.raises(ValueError, match='Frozen v3 code changed'):
        live.check_frozen()
