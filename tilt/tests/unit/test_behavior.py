import numpy as np
import pandas as pd
import pytest

from tilt.features import behavior
from tilt.features.model_features import ALL_LF_COLUMNS, forbidden


def history(rates, speed='blitz', player='a', gap=1000, start=0):
    rows = []
    for i, rate in enumerate(rates):
        s = start + i * gap
        rows.append(dict(player=player, game_id=f'{player}{i:03d}', speed=speed, start_ms=s, end_upper_ms=s + gap - 1,
                         attack_rate=rate, risk_rate=rate, defensive_rate=rate, style_switch_rate=rate))
    return pd.DataFrame(rows)


def by_game(frame, game):
    return frame.set_index('game_id').loc[game]


def test_cold_start_is_missing_not_a_cohort_baseline():
    out = behavior.personal_deviations(history([.2, .3, .4, .5, .6]))
    assert out[list(behavior.DEVIATIONS)].isna().all().all()
    six = behavior.personal_deviations(history([.2, .3, .4, .5, .6, .9]))
    assert by_game(six, 'a005').attack_delta_personal == pytest.approx(.9 - .4)


def test_zero_mad_uses_the_floor():
    out = behavior.personal_deviations(history([.3] * 5 + [.4]))
    assert by_game(out, 'a005').risk_z_personal == pytest.approx(.1 / behavior.FLOOR)


def test_only_games_ended_before_the_start_are_history():
    games = history([.1] * 5 + [.9])
    # A game that overlaps the current one (ends after it starts) must not count.
    overlapping = dict(player='a', game_id='a999', speed='blitz', start_ms=games.start_ms.iloc[-1] - 10,
                       end_upper_ms=games.start_ms.iloc[-1] + 10, attack_rate=1., risk_rate=1.,
                       defensive_rate=1., style_switch_rate=1.)
    out = behavior.personal_deviations(pd.concat([games, pd.DataFrame([overlapping])]))
    row = by_game(out, 'a005')
    assert row.attack_delta_personal == pytest.approx(.8)
    assert row.history_end_max < games.start_ms.iloc[-1]


def test_history_is_per_speed_and_capped():
    blitz = history([.1] * 5 + [.5], speed='blitz')
    rapid = history([.9] * 5, speed='rapid', start=10**7)
    out = behavior.personal_deviations(pd.concat([blitz, rapid]))
    assert by_game(out, 'a005').attack_delta_personal == pytest.approx(.4)
    capped = behavior.personal_deviations(history([1.] * 10 + [0.] * behavior.CAP + [.5]))
    assert by_game(capped, f'a{10 + behavior.CAP:03d}').attack_delta_personal == pytest.approx(.5)


def moves(flags, player='a', game='g'):
    n = len(flags['attack'])
    return pd.DataFrame(dict(player=player, game_id=game, ply=np.arange(1, 2 * n, 2), **flags))


def test_short_games_have_no_trend_or_change_point():
    out = behavior.game_dynamics(moves({f: [0, 1, 0, 1] for f in behavior.FLAGS})).iloc[0]
    assert np.isnan(out.attack_trend_3w) and np.isnan(out.behavior_change_point) and np.isnan(out.style_entropy)
    assert out.attack_rate_p40 == pytest.approx(.5)


def test_dynamics_on_a_known_sequence():
    n = 30
    attack = [0] * 10 + [1] * 10 + [1] * 10
    risk = [0] * 15 + [1] * 15
    out = behavior.game_dynamics(moves(dict(attack=attack, risk=risk, defensive=[0] * n, style_switch=[0] * n))).iloc[0]
    assert out.attack_trend_3w == pytest.approx(1.)
    assert out.behavior_change_point == pytest.approx(1.)
    assert 0 < out.style_entropy <= 1
    # One run of 0s then one run of 1s: lag-1 autocorrelation is high but below 1 (the pair at the boundary).
    expected = np.corrcoef(np.array(attack[:-1], float), np.array(attack[1:], float))[0, 1]
    assert out.behavior_persistence == pytest.approx(expected) and expected > .9
    # Own moves at plies 1, 3, ..., 39 are the prefix: the first 20 moves.
    assert out.attack_rate_p40 == pytest.approx(.5)
    assert out.risk_rate_p40 == pytest.approx(5 / 20)


def test_one_kind_of_move_has_zero_entropy():
    n = 12
    out = behavior.game_dynamics(moves(dict(attack=[1] * n, risk=[0] * n, defensive=[0] * n, style_switch=[0] * n))).iloc[0]
    assert out.style_entropy == 0
    assert np.isnan(out.behavior_persistence)


def test_candidate_names_pass_the_existing_guard():
    for column in behavior.FEATURES:
        assert not forbidden(column, strict=True), column
        assert column not in ALL_LF_COLUMNS
