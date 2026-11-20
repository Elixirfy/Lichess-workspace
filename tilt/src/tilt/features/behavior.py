"""Phase 2 behavioural candidates (reports/phase2_features.md).

Only geometry move flags are read: attack (capture, check or a square next to the enemy king), risk (the moved piece
can be taken), defensive (the player was in check) and style_switch (risk differs from the player's previous move).
No engine evaluation, clock, rating, result or LF input is read. The prediction point is game completion, so every
move of the current game is available; personal baselines use only games that ended before the current one began.
"""
import numpy as np
import pandas as pd

FLAGS = ('attack', 'risk', 'defensive', 'style_switch')
RATES = tuple(f'{f}_rate' for f in FLAGS)
FLOOR = .05          # Same rate floor as features.GAME_BASELINES: MAD = 0 never divides by zero.
MIN_GAMES = 5        # Same as compute(min_prior_games=5): fewer prior games is a cold start (NaN).
CAP = 200            # Same as compute(max_history_games=200), per speed.
PREFIX_PLIES = 40    # The weak labels decide every labelled game shorter than 40 plies (Phase 1).
MIN_PART_MOVES = 3   # Each third of the game needs this many own moves.
MIN_SEGMENT = 5      # Change point: each side of the split needs this many own moves.
CATEGORIES = 4       # attack, risk, defensive, quiet

DYNAMICS = ('attack_trend_3w', 'risk_volatility_3w', 'style_entropy', 'behavior_change_point',
            'behavior_persistence', 'attack_rate_p40', 'risk_rate_p40', 'defensive_rate_p40', 'style_switch_rate_p40')
DEVIATIONS = tuple(f'{f}_{kind}_personal' for f in FLAGS for kind in ('delta', 'z'))
FEATURES = DEVIATIONS + DYNAMICS


def thirds(values):
    if len(values) < 3 * MIN_PART_MOVES:
        return None
    return [part.mean() for part in np.array_split(np.asarray(values, dtype=float), 3)]


def entropy(attack, risk, defensive):
    """Normalised Shannon entropy of the move mix; attack takes precedence, then risk, then defensive."""
    category = np.where(attack, 0, np.where(risk, 1, np.where(defensive, 2, 3)))
    p = np.bincount(category, minlength=CATEGORIES) / len(category)
    p = p[p > 0]
    return float(-(p * np.log2(p)).sum() / np.log2(CATEGORIES))


def change_point(values):
    """Largest |mean after - mean before| over single splits that leave MIN_SEGMENT moves on each side,
    taken at the split with the least squared error (one mean shift)."""
    x = np.asarray(values, dtype=float)
    n = len(x)
    if n < 2 * MIN_SEGMENT:
        return np.nan
    cumulative, squares = np.cumsum(x), np.cumsum(x * x)
    k = np.arange(MIN_SEGMENT, n - MIN_SEGMENT + 1)
    left, right = cumulative[k - 1], cumulative[-1] - cumulative[k - 1]
    sse = (squares[-1] - left ** 2 / k - right ** 2 / (n - k))
    best = k[np.argmin(sse)]
    return float(abs(x[best:].mean() - x[:best].mean()))


def persistence(values):
    """Lag-1 autocorrelation of the attack flag: does attacking come in runs?"""
    x = np.asarray(values, dtype=float)
    if len(x) < 2 * MIN_PART_MOVES or x[:-1].std() == 0 or x[1:].std() == 0:
        return np.nan
    return float(np.corrcoef(x[:-1], x[1:])[0, 1])


def game_dynamics(moves):
    """One row per (player, game_id) from the player's own moves: game_id, player, ply and the four flags."""
    moves = moves.sort_values(['player', 'game_id', 'ply'])
    rows = []
    for (player, game), own in moves.groupby(['player', 'game_id'], sort=False):
        flags = {f: own[f].fillna(0).astype(float).to_numpy() for f in FLAGS}
        attack_parts, risk_parts = thirds(flags['attack']), thirds(flags['risk'])
        prefix = own.ply.to_numpy() <= PREFIX_PLIES
        row = dict(player=player, game_id=game,
                   attack_trend_3w=attack_parts[2] - attack_parts[0] if attack_parts else np.nan,
                   risk_volatility_3w=float(np.std(risk_parts)) if risk_parts else np.nan,
                   style_entropy=entropy(flags['attack'], flags['risk'], flags['defensive'])
                   if len(own) >= 2 * MIN_PART_MOVES else np.nan,
                   behavior_change_point=change_point(flags['risk']),
                   behavior_persistence=persistence(flags['attack']))
        for f in FLAGS:
            row[f'{f}_rate_p40'] = float(flags[f][prefix].mean()) if prefix.any() else np.nan
        rows.append(row)
    return pd.DataFrame(rows, columns=['player', 'game_id', *DYNAMICS])


def personal_deviations(games):
    """Per player and speed: current rate minus the median of up to CAP prior games that ended before this game
    started, and that difference over max(1.4826 MAD, FLOOR). Fewer than MIN_GAMES prior values is a cold start."""
    out = []
    for _, group in games.groupby(['player', 'speed'], sort=False):
        # The pipeline's PriorHistory activates games from a heap keyed (end_upper_ms, game_id).
        order = group.sort_values(['end_upper_ms', 'game_id'], kind='stable')
        ends = order.end_upper_ms.to_numpy(dtype=float)
        values = {r: order[r].to_numpy(dtype=float) for r in RATES}
        for _, game in group.iterrows():
            available = int(np.searchsorted(ends, game.start_ms, side='left')) if pd.notna(game.start_ms) else 0
            window = slice(max(0, available - CAP), available)
            row = dict(player=game.player, game_id=game.game_id,
                       history_end_max=float(ends[window].max()) if available else np.nan)
            for flag, rate in zip(FLAGS, RATES):
                prior = values[rate][window]
                prior = prior[np.isfinite(prior)]
                current = game[rate]
                if len(prior) < MIN_GAMES or not np.isfinite(current):
                    row[f'{flag}_delta_personal'] = row[f'{flag}_z_personal'] = np.nan
                    continue
                median = float(np.median(prior))
                scale = max(1.4826 * float(np.median(np.abs(prior - median))), FLOOR)
                row[f'{flag}_delta_personal'] = current - median
                row[f'{flag}_z_personal'] = (current - median) / scale
            out.append(row)
    return pd.DataFrame(out, columns=['player', 'game_id', 'history_end_max', *DEVIATIONS])


def build(moves, games):
    """All Phase 2 candidates, one row per (player, game_id)."""
    dynamics = game_dynamics(moves[['player', 'game_id', 'ply', *FLAGS]])
    deviations = personal_deviations(games[['player', 'game_id', 'speed', 'start_ms', 'end_upper_ms', *RATES]])
    return deviations.merge(dynamics, on=['player', 'game_id'], how='outer', validate='one_to_one')
