"""Honest held-out agreement with behavioural weak labels, never emotion accuracy."""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score,
                             mean_absolute_error, precision_score, recall_score, roc_auc_score)

from ..data import storage
from ..core.train import aligned, predict_bundle
from ..labels.weak_labels import outcome_gate, partition_balance, SPLIT_POLICY, WEAK_VERSION
from ..features.model_features import passes_audits


def metrics(frame, threshold):
    frame = frame[frame.weak_tilt_label.notna() & np.isfinite(frame.predicted_weak_tilt_prob)]
    if frame.empty:
        return dict(n=0)
    y = frame.weak_tilt_label.to_numpy(dtype=int)
    p = frame.predicted_weak_tilt_prob.to_numpy(dtype=float)
    pred = p >= threshold
    difference = frame.predicted_weak_tilt_score_regression.to_numpy(dtype=float) - 100 * frame.weak_tilt_prob.to_numpy(dtype=float)
    return dict(n=len(y), positives=int(y.sum()), precision=float(precision_score(y, pred, zero_division=0)),
                recall=float(recall_score(y, pred, zero_division=0)), f1=float(f1_score(y, pred, zero_division=0)),
                roc_auc=float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else None,
                pr_auc=float(average_precision_score(y, p)) if len(np.unique(y)) == 2 else None,
                mae=float(np.abs(difference).mean()), rmse=float(np.sqrt((difference ** 2).mean())),
                brier=float(brier_score_loss(y, p)))


def outcome_metrics(frame, threshold):
    known = frame[frame.result_score.notna()]
    return {name: metrics(known.loc[mask], threshold) for name, mask in (
        ('losses', known.result_score.eq(0)), ('non_losses', known.result_score.ne(0)))}


def beats_baselines(result, baselines):
    """Point-estimate comparison only; undefined stratum AUC prevents a claim."""
    if {b['model'] for b in baselines} != {'class_prior', 'losing_streak', 'result_only'}:
        return False
    def better(a, b, keys):
        return all(a.get(k) is not None and b.get(k) is not None and a[k] > b[k] for k in keys)
    return all(better(result['test'], b['test'], ('pr_auc', 'f1', 'roc_auc')) and all(
        better(result['outcome_strata']['test'][name], b['outcome_strata']['test'][name], ('roc_auc',))
        for name in ('losses', 'non_losses')) for b in baselines)


def bootstrap(frame, threshold, repetitions=100, seed=42):
    """Player-cluster bootstrap; retains within-player dependence in either split."""
    frame = frame[frame.weak_tilt_label.notna() & np.isfinite(frame.predicted_weak_tilt_prob)].reset_index(drop=True)
    groups = [g.index.to_numpy() for _, g in frame.groupby('player_id')]
    if len(groups) < 2:
        return dict(status='unavailable: fewer than two test-player clusters')
    rng, samples = np.random.default_rng(seed), []
    for _ in range(repetitions):
        ids = np.concatenate([groups[i] for i in rng.integers(len(groups), size=len(groups))])
        samples.append(metrics(frame.iloc[ids], threshold))
    ci = {}
    for key in ('precision', 'recall', 'f1', 'roc_auc', 'pr_auc', 'mae', 'rmse', 'brier'):
        values = [s[key] for s in samples if s.get(key) is not None]
        ci[key] = [float(v) for v in np.percentile(values, [2.5, 97.5])] if values else None
    ci.update(clusters=len(groups), repetitions=repetitions)
    return ci


def reliability(frame):
    frame = frame[frame.weak_tilt_label.notna() & np.isfinite(frame.predicted_weak_tilt_prob)].copy()
    frame['bin'] = np.minimum((frame.predicted_weak_tilt_prob * 10).astype(int), 9)
    return [dict(bin=f'{i/10:.1f}–{(i+1)/10:.1f}', n=len(g),
                 predicted=float(g.predicted_weak_tilt_prob.mean()), observed=float(g.weak_tilt_label.mean()))
            for i, g in frame.groupby('bin')]


def permutation(bundle, frame, repetitions=3):
    if frame.empty or frame.weak_tilt_label.nunique() < 2:
        return []
    rng = np.random.default_rng(42)
    y = frame.weak_tilt_label.astype(int)
    base = average_precision_score(y, predict_bundle(bundle, frame)[0])
    result = []
    for col in bundle['features']:
        changes = []
        for _ in range(repetitions):
            shuffled = frame.copy()
            shuffled[col] = rng.permutation(frame[col].to_numpy())
            changes.append(float(base - average_precision_score(y, predict_bundle(bundle, shuffled)[0])))
        result.append(dict(feature=col, pr_auc_drop=float(np.mean(changes)), std=float(np.std(changes))))
    return sorted(result, key=lambda r: -r['pr_auc_drop'])


def contributions(bundle, frame, columns=None):
    """Reference replacement sensitivities in score points; not additive SHAP."""
    prob = predict_bundle(bundle, frame)[0]
    columns = columns or bundle['features']
    changes = {}
    for col in columns:
        replaced = frame.copy()
        replaced[col] = bundle['reference'][bundle['features'].index(col)]
        changes[col] = 100 * (prob - predict_bundle(bundle, replaced)[0])
    result = []
    for i in range(len(frame)):
        top = sorted(changes, key=lambda c: -abs(changes[c][i]))[:3]
        result.append([dict(feature=c, score_delta=float(changes[c][i])) for c in top])
    return result


def fmt(value):
    return 'NA' if value is None else f'{value:.3f}' if isinstance(value, (float, np.floating)) else str(value)


def table(lines, headers, rows):
    lines.extend(['', '| ' + ' | '.join(headers) + ' |', '|' + '|'.join('---' for _ in headers) + '|'])
    lines.extend('| ' + ' | '.join(fmt(v) for v in row) + ' |' for row in rows)
    lines.append('')


def run(data, bootstrap_repetitions=100):
    data = Path(data)
    manifest = json.loads((data / 'processed/models/manifest.json').read_text())
    if manifest.get('status') != 'complete':
        raise ValueError('Training is incomplete; finish train before evaluate')
    if manifest['weak_manifest'] != json.loads((data / 'processed/out/weak_manifest.json').read_text()):
        raise ValueError('Weak labels changed since training; rerun train before evaluate')
    weak = manifest['weak_manifest']
    if weak.get('version') != WEAK_VERSION or any(k not in manifest for k in ('outcome_proxy_audits', 'lf_proxy_audits')):
        raise ValueError('Rebuild weak labels and train with the revised pipeline on the compute machine')
    if weak.get('split_policy') != SPLIT_POLICY or any(
            'threshold' not in r or 'threshold_source' not in r for r in manifest['runs']):
        raise ValueError('Rebuild weak labels and train with revised splits and stored thresholds on the compute machine')
    results, predictions = {}, {}
    for run in manifest['runs']:
        threshold = run['threshold']
        frame = pd.read_parquet(data / 'processed' / 'out' / f"predictions__{run['id']}.parquet")
        test = frame[(frame.split == 'test') & frame.weak_tilt_label.notna()]
        val = frame[(frame.split == 'validation') & frame.weak_tilt_label.notna()]
        predictions[run['id']] = frame
        result = dict(**run, test=metrics(test, threshold), validation=metrics(val, threshold),
                      ci=bootstrap(test, threshold, bootstrap_repetitions), reliability=reliability(test),
                      outcome_strata=dict(test=outcome_metrics(test, threshold), validation=outcome_metrics(val, threshold)), breakdowns={})
        test = test.copy()
        test['rating_band'] = test.rating.map(lambda x: f'{int(x // 200) * 200}–{int(x // 200) * 200 + 199}' if pd.notna(x) else 'missing')
        for column in ('speed', 'rating_band'):
            result['breakdowns'][column] = {str(key): metrics(group, threshold) for key, group in test.groupby(column, dropna=False)}
        results[run['id']] = result
    # Choose exclusively by validation average precision, never test metrics.
    choices = {}
    for split in ('by_player', 'by_time'):
        candidates = [r for r in manifest['runs'] if r['split'] == split and r['model'] in ('random_forest', 'xgboost', 'lightgbm') and r['variant'] != 'baseline'
                      and passes_audits(r.get('features'), manifest['outcome_proxy_audits'].get(split, []),
                                        manifest['lf_proxy_audits'].get(split, []))
                      and results[r['id']]['validation'].get('pr_auc') is not None]
        if candidates:
            winner = max(candidates, key=lambda r: results[r['id']]['validation']['pr_auc'])
            choices[split] = winner['id']
    importance = []
    selected = choices.get('by_player')
    for selected_id in choices.values():
        selected_test = predictions[selected_id]
        selected_test = selected_test[(selected_test.split == 'test') & selected_test.weak_tilt_label.notna()].copy()
        selected_test['rating_band'] = selected_test.rating.map(lambda x: f'{int(x // 200) * 200}–{int(x // 200) * 200 + 199}' if pd.notna(x) else 'missing')
        for column in ('speed', 'rating_band'):
            for key, group in selected_test.groupby(column, dropna=False):
                results[selected_id]['breakdowns'][column][str(key)]['ci'] = bootstrap(group, results[selected_id]['threshold'], bootstrap_repetitions)
    if selected:
        bundle = joblib.load(data / 'processed' / 'models' / f'{selected}.joblib')
        frame = aligned(data)
        val = frame[(frame.split == 'validation') & frame.weak_tilt_label.notna()]
        importance = permutation(bundle, val)
        test = frame[frame.split == 'test'].copy()
        if len(test):
            factors = contributions(bundle, test, [r['feature'] for r in importance[:12]] or None)
            export = test[['player_id', 'game_id']].copy()
            export['weak_model_top_factors'] = [json.dumps(f) for f in factors]
            storage.write_frame(data / 'processed/out/weak_prediction_factors.parquet', export)
    selection_diagnostics = {split: dict(validation_positives=results[key]['validation_positives'],
                                        warning='Fewer than 30 validation weak positives; model selection may be unstable'
                                        if results[key]['validation_positives'] < 30 else None)
                             for split, key in choices.items()}
    selection = dict(title='Tilt weak-label model', selected=choices, diagnostics=selection_diagnostics, training_run_id=manifest['training_run_id'],
                     status='validation-selected tree model' if selected else 'No valid unseen-player validation selection; score unavailable')
    (data / 'processed/models/selection.json').write_text(json.dumps(selection, indent=2))
    summary = dict(title='Tilt weak-label model', results=results, selection=selection, permutation_importance=importance,
                   outcome_gates={name: stats['outcome_gate'] for name, stats in weak['splits'].items()},
                   outcome_proxy_audits=manifest['outcome_proxy_audits'], lf_proxy_audits=manifest['lf_proxy_audits'])
    (data / 'processed/out/weak_metrics.json').write_text(json.dumps(summary, indent=2, allow_nan=False))
    lines = ['# Tilt weak-label model', '',
             '**Labels are behavioural proxies, not measured emotions. Every metric below measures agreement with weak labels, not real emotion. There are no human validation labels.**', '',
             f"Cohort: {weak['players']} sampled players; {weak['games']} distinct games; {weak['rows']} player-game rows. Opponents without their own sampled history are excluded.",
             'Real-data sampling: October 2026 monthly dump, 200-point blitz rating strata from 400 to 3000; bots and ToS-flagged accounts removed. Sampling favours active players (at least 12 blitz games in the first approximately 600,000 monthly games), so results do not represent all Lichess players.',
             'The cohort description applies to the intended real dataset; a scratch smoke run is only an implementation check. Inspect cohort counts before interpreting any results.', '',
             '## Weak label construction', '',
             'Train-only symmetric Dawid–Skene EM conditional on non-abstain votes. Abstentions contribute zero evidence. Fixed balanced prior = .5; Beta(6,2) accuracy pseudocounts and accuracy clipped to [.500001, .999999] preserve LF polarity. No-vote rows stay unlabelled. Estimated LF accuracies are latent model assumptions, not measured accuracy; zero-vote LF estimates are prior-only. Correlation, outcome selection and nonidentifiability can cause overconfidence. Thresholds and input provenance are in WEAK_LABELS.md.']
    if any(stats['outcome_gate']['failed'] for stats in weak['splits'].values()):
        lines[4:4] = ['**FAILED: label ≈ outcome — the train-label gate failed. Weak-model utility is unproven.**', '']
    for name, stats in weak['splits'].items():
        lines.extend(['', f'### {name}', '',
                      f"Labelled {stats['labelled_rows']}/{weak['rows']}; positives {stats['positive_rows']} ({stats['positive_rows']/max(1, stats['labelled_rows']):.1%}). Coverage {stats['coverage']:.3f}; overlap {stats['overlap']:.3f}; conflict {stats['conflict']:.3f}.",
                      f"Partition counts (before excluding abstentions): {json.dumps(stats['partitions'], sort_keys=True)}.",
                      f"Secondary player-session units: {stats['session_statistics']['rows']}; labelled {stats['session_statistics']['labelled_rows']}. Session pooling uses any positive vote per LF, otherwise any negative; a separate session EM is fitted on train sessions. No session predictor is trained."])
        f = pd.read_parquet(data / 'processed' / 'out' / f'weak_{name}.parquet')
        gate = outcome_gate(f.query('split == "train"'))
        lines.extend(['', '**' + gate['status'] + '**',
                      f"Train-label agreement with lost: {fmt(gate['agreement'])}. Gate fails above .75 agreement, or below 10% of either weak class in either outcome stratum. Empty strata fail. Unknown outcomes are excluded."])
        table(lines, ['Train outcome', 'Labelled N', 'Weak-TILT rate', 'Weak-NOT_TILT rate'],
              [[key, g['n'], g['weak_tilt_rate'], g['weak_not_tilt_rate']] for key, g in gate['strata'].items()])
        table(lines, ['LF', 'Votes', 'Coverage', 'Overlap rows', 'Conflict rows', 'Estimated accuracy'],
              [[r[k] for k in ('name', 'votes', 'coverage', 'overlap', 'conflict', 'estimated_accuracy')] for r in stats['lfs']])
        balance = partition_balance(f)
        table(lines, ['Partition', 'Players', 'Rows', 'Labelled rows', 'Weak positives', 'Positive rate'],
              [[p, b['players'], b['rows'], b['labelled'], b['positives'],
                f"{b['positive_rate']:.1%}" if b['positive_rate'] is not None else None]
               for p in ('train', 'validation', 'test') for b in [balance[p]]])
        covered = f.weak_tilt_label.notna()
        majority = (f.weak_majority_prob >= .5).astype(int)
        agreement = float((majority[covered] == f.loc[covered, 'weak_tilt_label']).mean()) if covered.any() else None
        lines.append(f'Majority-vote baseline agreement with EM on covered rows: {fmt(agreement)}. Ties vote TILT; majority vote is a label-combination baseline, not an emotion benchmark.')
    lines.extend(['', '## Evaluation design', '',
                  'Stable player hash split approximately 60/20/20; no target player in more than one partition. Shared predicted games and future label-dependency games are purged from earlier-priority partitions. Time cutoffs are 70/85 percentiles of unique start times (approximately 70/15/15 before purging); the complete label-evidence horizon must finish before a cutoff. Unknown ends and crossing scopes are excluded. Unlabelled strictly prior personal history is permitted for held-out players. Partition tables count distinct players across all retained rows and positive rates among labelled rows.',
                  f"Time cutoffs (UTC epoch ms): {json.dumps(weak['cutoffs'])}.",
                  'All preprocessing and both proxy audits fit train rows only, including unlabelled train rows for audits. Classification uses balanced training weights (LSTM positive-class loss weight); regression fits 100 × weak_tilt_prob without class weights. Seeds = 42. Validation-only Platt calibration falls back to identity with fewer than 20 rows, fewer than 10 weak positives, one class, or a nonpositive slope. LSTM uses up to eight completed-game snapshots including the current game, with overlaps excluded. CPU only.',
                  'Each trained run chooses its decision threshold on calibrated validation scores to maximise F1, breaking ties by the higher threshold. Diagnostics apply the same rule to their own unchanged scores. With fewer than 10 validation weak positives or only one scored class, use the labelled-train score quantile (after calibration where applicable) at 1 minus the train weak-positive rate (higher order statistic). Predictions use score >= threshold; tied scores, including the constant class prior, can prevent an exact positive-rate match. Test rows never choose thresholds. Every binary metric and bootstrap sample uses the stored threshold. Tree selection remains validation PR-AUC; fewer than 30 validation positives trigger a warning.',
                  'Prediction point is game completion. Outcome/status, current engine-quality/adverse-event feature families, their baselines and original mixed BDS are withheld. A safe BDS is recomputed from retained deviations; LF timing/rating families are also withheld. clock_fraction_last is prohibited in every variant. The strict LF ablation additionally removes future-signal analogues and related context. Recent result form is excluded where it shares LF provenance; this deliberately limits the requested context inputs.',
                  'PR-AUC is average precision. MAE/RMSE are on the 0–100 soft weak target. Brier/reliability use hard weak labels. Bootstrap is by player cluster; 95% percentile intervals condition on the fitted models and label model. Small/single-class strata have undefined AUCs; fewer than two clusters have no CI. Intervals do not capture label uncertainty.'])
    lines.extend(['', '## Train-only outcome-proxy audit', '',
                  'Every candidate model input is audited on train rows only, including unlabelled rows. Targets: loss and status == outoftime (time forfeit; timeout means abandonment). Scores are max(AUC, 1−AUC), after train-median imputation. Missing indicators are also audited because the imputer exposes them. Every variant excludes a feature if any score exceeds .70 or a target AUC is unavailable. Validation/test never set exclusions. Full audit is in weak_metrics.json and models/manifest.json.'])
    for split, audit in manifest['outcome_proxy_audits'].items():
        lines.append('### ' + split + ' (top 15 by maximum AUC)')
        lines.append('Features removed by outcome audit (every variant): ' + ', '.join(r['feature'] for r in audit if r['exclude_strict']) + '.')
        table(lines, ['Feature', 'Lost AUC', 'Time-forfeit AUC', 'Lost missing AUC', 'Time-forfeit missing AUC', 'Excluded strict'],
              [[r[k] for k in ('feature', 'lost_auc', 'time_forfeit_auc', 'lost_missing_auc', 'time_forfeit_missing_auc', 'exclude_strict')] for r in audit[:15]])
    lines.extend(['', '## Train-only LF-provenance proxy audit', '',
                  'Every candidate is compared with every LF source quantity on train rows only, including unlabelled rows. Absolute Spearman correlation ≥.60 excludes the input from every variant. Audit metadata includes current/past/future quantities, exact terminal/adverse summaries, move-source min/max/mean, game length and temporal differences. Status uses train-category indicators. Observed pairs, median-imputed values and missing indicators are checked; constant/unavailable pairs have null correlation. No phase-fraction exceptions. Model selection checks actual retained features against both audits and rejects unassessed features. Full per-feature strongest matches are in weak_metrics.json and models/manifest.json.'])
    for split, audit in manifest['lf_proxy_audits'].items():
        lines.extend(['', '### ' + split + ' (top 15 by absolute Spearman)',
                      'Features removed by LF-provenance audit (every variant): ' + ', '.join(r['feature'] for r in audit if r['exclude']) + '.'])
        table(lines, ['Feature', 'LF quantity', 'Representation', 'Spearman rho', 'Absolute rho', 'Paired N', 'Excluded'],
              [[r[k] for k in ('feature', 'lf_quantity', 'representation', 'rho', 'abs_rho', 'n', 'exclude')] for r in audit[:15]])
    for split in ('by_player', 'by_time'):
        lines.extend(['', '## Unseen players' if split == 'by_player' else '## Time split'])
        runs = [r for r in manifest['runs'] if r['split'] == split]
        table(lines, ['Model', 'Variant', 'Threshold', 'Threshold source', 'Validation weak positives', 'Calibration'],
              [[r['model'], r['variant'], repr(r['threshold']), r['threshold_source'], r['validation_positives'], r['calibration']] for r in runs])
        # Outcome-stratum results precede aggregate metrics so outcome confounding
        # cannot be hidden by the aggregate score. Include every diagnostic.
        for partition in ('test', 'validation'):
            for stratum in ('losses', 'non_losses'):
                lines.append(f'### {partition}: {stratum} only — every model and diagnostic')
                table(lines, ['Model', 'Variant', 'N', 'Precision', 'Recall', 'F1', 'ROC-AUC', 'PR-AUC', 'MAE', 'RMSE', 'Brier'],
                      [[r['model'], r['variant']] + [results[r['id']]['outcome_strata'][partition][stratum].get(k)
                       for k in ('n', 'precision', 'recall', 'f1', 'roc_auc', 'pr_auc', 'mae', 'rmse', 'brier')] for r in runs])
        lines.append('### Aggregate test metrics')
        table(lines, ['Model', 'Variant', 'N', 'Precision', 'Recall', 'F1', 'ROC-AUC', 'PR-AUC', 'MAE', 'RMSE', 'Brier'],
              [[r['model'], r['variant']] + [results[r['id']]['test'].get(k) for k in ('n', 'precision', 'recall', 'f1', 'roc_auc', 'pr_auc', 'mae', 'rmse', 'brier')] for r in runs])
        for run in runs:
            result = results[run['id']]
            ci = result['ci']
            lines.append(f"{run['model']}/{run['variant']}: calibration: {run['calibration']}; test F1 CI {ci.get('f1', ci.get('status'))}; PR-AUC CI {ci.get('pr_auc', ci.get('status'))}.")
        selected_split = choices.get(split)
        if selected_split:
            result = results[selected_split]
            lines.extend(['', f"Validation-selected tree: `{selected_split}`; validation weak positives: {result['validation_positives']}."])
            if selection_diagnostics[split]['warning']:
                lines.append('**Warning: ' + selection_diagnostics[split]['warning'] + '.**')
            baselines = [r for r in runs if r['variant'] == 'baseline']
            beats = beats_baselines(result, [results[r['id']] for r in baselines]) and not weak['splits'][split]['outcome_gate']['failed']
            lines.append('The selected model beats class_prior, losing_streak and result_only on aggregate test PR-AUC, F1 and ROC-AUC, and on ROC-AUC within both outcome strata (point estimates only). This does not validate emotion detection.' if beats else 'No beats-baselines claim: superiority to class_prior, losing_streak and result_only on aggregate metrics and both within-outcome ROC-AUCs is not established, or the train-label gate failed. Undefined AUCs cannot support a claim.')
            table(lines, ['Probability bin', 'N', 'Mean prediction', 'Weak positive fraction'],
                  [[r[k] for k in ('bin', 'n', 'predicted', 'observed')] for r in result['reliability']])
            for column, breakdown in result['breakdowns'].items():
                lines.append(f'### Selected model by {column}')
                subgroup_rows = []
                for key, m in breakdown.items():
                    for label, values in [(result['model'] + '/' + result['variant'], m)] + [
                        (r['model'], results[r['id']]['breakdowns'][column].get(key, {})) for r in baselines]:
                        subgroup_rows.append([key, label] + [values.get(k) for k in ('n', 'precision', 'recall', 'f1', 'roc_auc', 'pr_auc', 'mae', 'rmse', 'brier')])
                table(lines, [column, 'Model', 'N', 'Precision', 'Recall', 'F1', 'ROC-AUC', 'PR-AUC', 'MAE', 'RMSE', 'Brier'], subgroup_rows)
    lines.extend(['', '## Personalisation, ML versus DL, and anti-circularity', '',
                  'The tables compare every tree and LSTM with/without explicit historical-baseline columns, and with the stricter LF-family ablation. The LSTM no_history variant still receives its causal recent-game sequence; it ablates baseline columns rather than the sequence itself. Differences are observational comparisons against the same weak target. Full per-model/per-stratum metrics and bootstrap intervals are in weak_metrics.json. The losing-streak and result_only diagnostics intentionally read LF-related outcome signals and are never eligible for selection or scoring. A two-encoder personalisation network is future work.'])
    table(lines, ['Split', 'Model', 'History ΔF1', 'History ΔPR-AUC', 'Strict ablation ΔPR-AUC'],
          comparison_rows(results))
    lines.extend(['', '## Explainability', '',
                  'Validation permutation importance for the selected unseen-player tree (average precision drop, three permutations). Correlated predictors may dilute importance. Per-prediction factors replace a feature with its train median and measure score change; these sensitivities are not causal or additive SHAP values. Factors for held-out games are in weak_prediction_factors.parquet.'])
    table(lines, ['Feature', 'PR-AUC drop', 'Permutation SD'], [[r['feature'], r['pr_auc_drop'], r['std']] for r in importance[:15]])
    lines.extend(['', '## Limitations and scoring', '',
                  'Weak labels are outcome-dependent and can confuse connectivity loss, rational resignation, fatigue, opponent strength or normal competitive requeueing with tilt. Sparse positive LFs and correlated negatives may collapse prevalence or yield confident but invalid probabilities. Excluding all-abstain rows causes selection bias. A score of 80 means calibrated agreement with the weak target, not an 80% probability of an emotion.',
                  'Calibration can be unstable with few validation players. Window/phase scores are exploratory prefix applications of a game-end model: they use only prefix moves and frozen prior baselines, but have no independently validated window targets or calibration. Treat timelines as descriptive model output. Full real-data runs are designed for two CPU threads; feature generation and Stockfish are never invoked by these commands.',
                  '## How to validate with human labels', '',
                  'Insert consented self-reports and expert labels with tilt.labels.insert_label, then run build-dataset. Its human-only out/labelled.parquet, by_player.parquet and by_time.parquet keep target_tilt (0–10) separate. Freeze this weak model and feature list, join by pseudonymous player_id/game_id for game-scope human annotations, and evaluate probability calibration, discrimination and score error against a preregistered human threshold (for example ≥5/10) and 10 × target_tilt. Preserve independent unseen-player/time partitions; do not train on the human test set. Moment and session labels require matching prediction scopes and their own models. Report inter-rater agreement, self/expert differences and uncertainty before combining raters. Then fine-tune/retrain on human training labels, recalibrate on human validation labels, and compare on the untouched human test set. Do not silently overwrite weak targets or copy them into labels.sqlite.',
                  '', f"Training seconds: {manifest['elapsed_seconds']:.1f}. Skipped runs: {json.dumps(manifest['skipped'])}."])
    (data / 'processed/out/MODEL_REPORT.md').write_text('\n'.join(lines) + '\n')
    return dict(report=str(data / 'processed/out/MODEL_REPORT.md'), selection=selection, runs=len(results))


def comparison_rows(results):
    rows = []
    for split in ('by_player', 'by_time'):
        for model in ('random_forest', 'xgboost', 'lightgbm', 'lstm'):
            keys = [f'{split}__{variant}__{model}' for variant in ('full', 'no_history', 'lf_ablated')]
            if not all(k in results for k in keys):
                continue
            a, b, c = (results[k]['test'] for k in keys)
            def delta(x, y, key):
                return x[key] - y[key] if x.get(key) is not None and y.get(key) is not None else None
            rows.append([split, model, delta(a, b, 'f1'), delta(a, b, 'pr_auc'), delta(c, a, 'pr_auc')])
    return rows
