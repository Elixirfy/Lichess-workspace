"""Synthetic evidence for proposal gates, polarity, provenance and TRAIN scope."""
import numpy as np
import pandas as pd
import pytest

from tilt.labels.weak_labels import ABSTAIN, LFS, LabelModel, vote as v1_vote
from tilt.labels.weak_labels_v2 import (DiagnosticLabelModel, LF_NAMES, SCHEMES, load_train,
                                       require_train, summary, vote, vote_matrix)


def context(plies=40, z=2.):
    return dict(plies=plies, move_count=plies // 2, status='mate', result_score=1,
                deviation_mean_cpl_z=z, adverse_events=2, mean_accuracy=90,
                baseline_mean_accuracy_median=80, mean_think=6., baseline_mean_think_median=10.,
                start_ms=61000, previous_end_upper_ms=1000,
                previous_result_score=0, previous_same_session=True,
                prior_session_loss_run=3, session_shrinking_gaps=True)


@pytest.mark.parametrize('scheme', SCHEMES)
@pytest.mark.parametrize('plies', [0, 19, 20, 39, 40, 59, 60, 79, 80, 160])
def test_both_classes_reachable_at_each_eligible_length(scheme, plies):
    positive, negative = context(plies), context(plies, z=0.)
    positive_votes, negative_votes = vote(positive, scheme), vote(negative, scheme)
    minimum = 40 if scheme == 'floor40' else 20
    if plies < minimum:
        assert set(positive_votes + negative_votes) == {ABSTAIN}
    else:
        assert 1 in positive_votes and 0 not in positive_votes
        assert 0 in negative_votes and 1 not in negative_votes


def test_floor40_is_exactly_v1_above_floor():
    for z in (np.nan, -2., 0., 1., 2.):
        row = context(40, z)
        assert vote(row, 'floor40') == v1_vote(row)
    assert len(vote({}, 'floor40')) == len(LFS)


@pytest.mark.parametrize('scheme', SCHEMES)
def test_missing_length_abstains_on_both_sides(scheme):
    for length in (None, pd.NA, np.nan, np.inf):
        row = context()
        row['plies'] = length
        assert vote(row, scheme) == [ABSTAIN] * len(LF_NAMES[scheme])


@pytest.mark.parametrize('scheme', ['symmetric20', 'speed_quality20'])
def test_own_move_sample_and_missing_evidence(scheme):
    row = context()
    for count in (0, 9, None, np.nan, np.inf):
        row['move_count'] = count
        assert vote(row, scheme) == [ABSTAIN] * len(LF_NAMES[scheme])
    assert vote({}, scheme) == [ABSTAIN] * len(LF_NAMES[scheme])
    row = context(z=np.nan)
    assert vote(row, scheme) == [ABSTAIN] * len(LF_NAMES[scheme])


@pytest.mark.parametrize('scheme', ['symmetric20', 'speed_quality20'])
def test_revised_calm_uses_rate_not_zero_events_or_length(scheme):
    for plies in (20, 40, 80):
        row = context(plies, z=1.)
        row['adverse_events'] = .25 * row['move_count']
        assert vote(row, scheme)[-1] == 0
        row['adverse_events'] += .001
        assert vote(row, scheme)[-1] == ABSTAIN
    for bad in (None, np.nan, -1):
        row = context(z=0.) | dict(adverse_events=bad)
        assert vote(row, scheme)[-1] == ABSTAIN


def test_speed_quality_has_no_result_status_session_or_future_reads():
    forbidden = {'result_score', 'previous_result_score', 'previous_same_session', 'status',
                 'prior_session_loss_run', 'session_shrinking_gaps', 'start_ms', 'end_upper_ms'}
    class Restricted(dict):
        def get(self, key, default=None):
            assert key not in forbidden and not key.startswith('next_')
            return super().get(key, default)
    for z, expected in [(2., [1, -1]), (0., [-1, 0])]:
        assert vote(Restricted(context(z=z)), 'speed_quality20') == expected
    for result in (0., .5, 1., None):
        assert vote(context() | dict(result_score=result, previous_result_score=result),
                    'speed_quality20') == [1, -1]


def test_after_loss_rules_still_require_session_gap_and_loss():
    row = context() | dict(prior_session_loss_run=0)
    assert vote(row, 'symmetric20')[:3] == [1, -1, 1]
    for patch in [dict(previous_result_score=1), dict(previous_same_session=False),
                  dict(previous_same_session=pd.NA), dict(previous_end_upper_ms=62000),
                  dict(start_ms=122000)]:
        assert vote(row | patch, 'symmetric20')[:3] == [-1, -1, -1]
    row = context(z=1.) | dict(prior_session_loss_run=0)
    assert vote(row, 'symmetric20')[:3] == [-1, -1, 1]


def test_speed_boundaries_and_invalid_baseline():
    row = context(z=1.5) | dict(mean_think=6.5)
    assert vote(row, 'speed_quality20')[0] == 1
    for patch in [dict(mean_think=6.5001), dict(mean_think=-1), dict(mean_think=None),
                  dict(baseline_mean_think_median=0), dict(baseline_mean_think_median=None),
                  dict(deviation_mean_cpl_z=1.4999)]:
        assert vote(row | patch, 'speed_quality20')[0] == ABSTAIN


def test_diagnostic_em_matches_v1_including_conflicts_and_empty_rows():
    votes = np.array([[1, -1, 1], [-1, 0, -1], [1, 0, -1], [-1, -1, -1]] * 12)
    old = LabelModel().fit(votes)
    new = DiagnosticLabelModel().fit(votes)
    np.testing.assert_allclose(new.accuracies, old.accuracies, rtol=0, atol=0)
    np.testing.assert_allclose(new.predict(votes), old.predict(votes), rtol=0, atol=0)
    assert new.state()['iterations'] <= 150
    limited = DiagnosticLabelModel().fit(votes, iterations=1)
    assert not limited.converged and limited.max_delta >= limited.tolerance
    empty = DiagnosticLabelModel().fit(np.full((3, 2), -1))
    assert empty.converged and empty.iterations_run == 0 and empty.fitted_rows == 0
    assert np.isnan(empty.predict(np.full((2, 2), -1))).all()
    with pytest.raises(ValueError):
        DiagnosticLabelModel().fit([[2]])


@pytest.mark.parametrize('parts', [None, ['validation'], ['test'], ['train', 'test'], [None]])
def test_all_statistics_fail_closed_on_non_train(parts):
    frame = pd.DataFrame({'x': [1]}) if parts is None else pd.DataFrame({'split': parts})
    for operation in (require_train, lambda f: vote_matrix(f, 'v1'),
                      lambda f: summary(f, np.empty((len(f), 2)), 'speed_quality20')):
        with pytest.raises(ValueError, match='TRAIN'):
            operation(frame)


def test_loader_projects_and_predicate_filters_before_exposing_data(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic.parquet'
    pd.DataFrame(dict(split=['train', 'test', 'validation'], weak_tilt_label=[0, 1, 1],
                      weak_tilt_prob=[.25, .75, .75], lf_input__plies=[30, 999, 888],
                      model_only_feature=[0, 999, 888])).to_parquet(source)
    original = pd.read_parquet
    def checked(path, **kwargs):
        assert kwargs['filters'] == [('split', '==', 'train')]
        assert 'model_only_feature' not in kwargs['columns']
        return original(path, **kwargs)
    monkeypatch.setattr(pd, 'read_parquet', checked)
    loaded = load_train(source)
    assert loaded.split.tolist() == ['train']
    assert loaded.lf_input__plies.tolist() == [30]


def test_summary_denominators_and_agreement_transitions():
    frame = pd.DataFrame(dict(split=['train'] * 4, weak_tilt_label=[1., 0., np.nan, 1.],
                              lf_input__plies=[20, 40, 80, 10], lf_input__result_score=[1, 0, .5, 0],
                              lf_input__previous_result_score=[1, 1, 0, 0]))
    votes = np.array([[1, -1], [-1, 0], [1, -1], [-1, -1]])
    r = summary(frame, votes, 'speed_quality20')
    assert r['coverage'] == .75 and r['tilt_rate'] == 2 / 3
    assert r['tilt_with_current_or_previous_loss_share'] == .5
    assert r['result']['win']['share_of_all_tilt'] == .5
    assert r['ply_buckets']['<20']['labelled'] == 0
    assert r['agreement_v1']['agreement'] == 1
    assert r['agreement_v1']['newly_labelled'] == r['agreement_v1']['lost_labels'] == 1
    assert sum(r['agreement_v1']['transitions'].values()) == 4


def test_unknown_scheme_is_rejected_even_when_frame_is_empty():
    with pytest.raises(ValueError, match='Unknown'):
        vote({}, 'typo')
    with pytest.raises(ValueError, match='Unknown'):
        vote_matrix(pd.DataFrame({'split': []}), 'typo')
