import json

import numpy as np
import pandas as pd
import pytest

from tilt.evaluation import eval_metrics


def synthetic(seed=0, players=60, games=12):
    rng = np.random.default_rng(seed)
    rows = []
    for p in range(players):
        split = 'train' if p < 36 else 'validation' if p < 48 else 'test'
        for g in range(games):
            plies = int(rng.integers(20, 120))
            attack = rng.random()
            label = float(plies < 40 or attack > .8) if rng.random() < .6 else np.nan
            start = (p * games + g) * 1000 if split == 'train' else 10**7 + (p * games + g) * 1000 if split == 'validation' else 2 * 10**7 + (p * games + g) * 1000
            rows.append(dict(player_id=f'p{p}', game_id=f'g{p}-{g}', split=split, weak_tilt_label=label,
                             start_ms=start, end_upper_ms=start + 500, lf_input__next_end_upper_ms=np.nan,
                             baseline_latest_end_ms=start - 1, lf_input__plies=plies,
                             result_score=float(rng.choice([0, .5, 1])), losing_streak_before=int(rng.integers(0, 3)),
                             history_games=g, initial_seconds=float(rng.choice([180, 300])),
                             increment_seconds=float(rng.choice([0, 2])), attack_rate=attack,
                             **{c: rng.random() for c in eval_metrics.E0 + eval_metrics.HISTORY
                                if c not in ('initial_seconds', 'increment_seconds', 'attack_rate')}))
    frame = pd.DataFrame(rows)
    for c in eval_metrics.SPEED:
        frame[c] = 1.0 if c == 'speed_blitz' else 0.0
    frame.loc[frame.history_games < 5, eval_metrics.HISTORY] = np.nan
    return frame


def write(folder, frame):
    folder.mkdir(parents=True, exist_ok=True)
    for split in eval_metrics.SPLITS:
        frame.to_parquet(folder / f'aligned_{split}.parquet', index=False)


def test_variants_follow_the_preregistration():
    assert len(eval_metrics.E0) == 16 and eval_metrics.MIDDLEGAME in eval_metrics.E0
    assert eval_metrics.MIDDLEGAME not in eval_metrics.VARIANTS['M1']['features']
    assert len(eval_metrics.VARIANTS['M1']['features']) == 15
    assert len(eval_metrics.HISTORY) == 13 and len(eval_metrics.VARIANTS['M2']['features']) == 28
    assert eval_metrics.VARIANTS['M2']['indicator'] is False
    assert len(eval_metrics.VARIANTS['M3']['features']) == 8


def test_a_player_in_two_splits_is_rejected():
    frame = synthetic()
    frame.loc[frame.index[0], 'split'] = 'test'
    with pytest.raises(ValueError, match='several splits'):
        eval_metrics.split_checks(frame, 'by_player')


def test_history_from_the_future_is_rejected():
    frame = synthetic()
    frame.loc[frame.index[3], 'baseline_latest_end_ms'] = frame.start_ms.iloc[3] + 1
    with pytest.raises(ValueError, match='future'):
        eval_metrics.split_checks(frame, 'by_time')


def test_test_labels_are_never_read(tmp_path):
    frame = synthetic()
    write(tmp_path / 'a', frame)
    poisoned = frame.copy()
    test = poisoned.split == 'test'
    poisoned.loc[test, 'weak_tilt_label'] = 1 - poisoned.loc[test, 'weak_tilt_label']
    write(tmp_path / 'b', poisoned)
    a = eval_metrics.run(tmp_path / 'a', tmp_path / 'out-a', repetitions=20)
    b = eval_metrics.run(tmp_path / 'b', tmp_path / 'out-b', repetitions=20)
    for split in eval_metrics.SPLITS:
        assert a[split]['validation'] == b[split]['validation']
        assert a[split]['paired_differences'] == b[split]['paired_differences']


def test_a_rerun_is_identical(tmp_path):
    write(tmp_path / 'a', synthetic())
    first = eval_metrics.run(tmp_path / 'a', tmp_path / 'one', repetitions=20)
    second = eval_metrics.run(tmp_path / 'a', tmp_path / 'two', repetitions=20)
    for key in ('decision', *eval_metrics.SPLITS):
        assert json.dumps(first[key], sort_keys=True) == json.dumps(second[key], sort_keys=True)
    assert (tmp_path / 'one/manifests/by_player.csv').read_text() == (tmp_path / 'two/manifests/by_player.csv').read_text()


def test_the_decision_rules_are_mechanical():
    def results(m1, m2, m3, e0=.5, length=.4):
        validation = {k: dict(pr_auc=v) for k, v in dict(M1=m1, M2=m2, M3=m3, E0=e0, **{'B-length': length}).items()}
        return {s: dict(validation=validation) for s in eval_metrics.SPLITS}
    accepted = eval_metrics.decide(results(.40, .46, .41))
    assert accepted['history']['accepted'] and accepted['cleanup']['use_m3']
    assert accepted['main'] == 'M3 + history'
    noise = eval_metrics.decide(results(.40, .44, .46))
    assert not noise['history']['accepted'] and not noise['cleanup']['use_m3'] and noise['main'] == 'M1'
