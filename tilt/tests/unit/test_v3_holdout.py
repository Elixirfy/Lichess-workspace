"""S5.8 synthetic fixtures; append-only file checks read metadata/bytes only."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np
import pandas as pd
import pytest

from tilt.evaluation import v3_holdout as h
from tilt.evaluation import v3_p3b as w, v3_train as t
from tilt.features import prefix_v3 as p
from tilt.labels import rules_v3, split_v3
from test_prefix_v3 import fixture as history_fixture
from test_v3_train import fixture as matrix_fixture


class Identity:
    def transform(self, values):
        return np.nan_to_num(np.asarray(values, float))


class Classifier:
    def predict_proba(self, values):
        prob = 1 / (1 + np.exp(-np.clip(values[:, 0], -20, 20)))
        return np.c_[1-prob, prob]


def bundle(features):
    return dict(format='phase5', features=list(features), imputer=Identity(),
                keep=np.arange(len(features)), scaler=Identity(), classifier=Classifier(),
                calibration=dict(model=None, status=t.NORMAL))


def scored_fixture():
    meta, pre, p20, reg, whole = matrix_fixture()
    meta['part'] = np.where(meta.player_id.str[-2:].astype(int) % 2, 'A_prime', 'B_prime')
    for f in (pre, p20, whole):
        f['part'] = f.player_id.map(meta.drop_duplicates('player_id').set_index('player_id').part)
    combined = h.adapt(pre).merge(h.adapt(p20), on=h.KEYS+['part'])
    bundles = {}
    for candidate in t.FITTED:
        heads = ('whole',) if candidate == 'P3-B/v3' else ('pre', 'p20')
        bundles[candidate] = dict(heads={head: bundle(w.FEATURES if head == 'whole' else t.matrix(
            combined if head == 'p20' else h.adapt(pre), head, candidate, reg).columns) for head in heads})
    return (meta, pre, p20, whole), reg, bundles, bundle(w.FEATURES)


def score_fixture():
    tables, reg, bundles, deployed = scored_fixture()
    return h.score_tables(*tables, reg, bundles, deployed)


def good_decision():
    metrics = dict(parts={part: {'all': {'M-v3::composite': dict(ece=.05)}} for part in h.PARTS})
    boot = {part: {s: {c: dict(ci=[.001,.02], point_delta=.01, repetitions=1000, skipped=100,
                             no_positive=80, one_class=20, rows=100, tilt=30)
                        for c in t.ADOPTION} for s in ('ge40','lt40')} for part in h.PARTS}
    return metrics, boot


def test_append_only_real_document_and_all_six_frozen_files():
    code = Path(__file__).resolve().parents[2]
    v3 = Path('/home/trantrien/tilt-labels-v3')
    # The operator exports this path so the same assertion works remotely.
    import os
    v3 = Path(os.environ.get('S5_V3', v3))
    args = SimpleNamespace(prereg=code/'reports/label_v3_preregistration.md', lock=v3/'prereg.sha256',
        s4_snapshot=v3/'S4/prereg_at_S4/label_v3_preregistration.md', s4_snapshot_lock=v3/'S4/prereg_at_S4/prereg.sha256',
        s3_snapshot=v3/'S3/prereg_at_S3/label_v3_preregistration.md', s3_snapshot_lock=v3/'S3/prereg_at_S3/prereg.sha256')
    h.verify_locks(args)
    assert h.whole is w and h.train is t and h.prefix is p
    assert h.rules is rules_v3 and h.split is split_v3
    expected = {**w.FROZEN,
        'evaluation/v3_train.py': 'ee8c3ca08f154d350da46c297677b0b898f9983b71ce1d879a4f7da53eae99b5',
        'evaluation/v3_p3b.py': '1fa43330c85884b3bdeab3ae6645a4beb9b46098962f51d1110fa1ebf3bffa0e',
        'data/cohort_v3.py': '08f33a448fdf199556fc879491eb4b9f3b9d3f6e4ed938c105d3e5c5dbd2dc9d'}
    for name, sha in expected.items():
        assert split_v3.sha(code/'src/tilt'/name) == sha
    assert w.code_hashes() == h.records(v3/'S4/run1/code_hash.txt')


@pytest.mark.parametrize('field', ['prereg','lock','s3_snapshot','s3_snapshot_lock','s4_snapshot','s4_snapshot_lock'])
def test_hash_or_snapshot_mismatch_stops(tmp_path, monkeypatch, field):
    s3, s4, current = b'S3', b'S3S4', b'S3S4S5'
    monkeypatch.setattr(h.split, 'PREREG_SHA', hashlib.sha256(s3).hexdigest())
    monkeypatch.setattr(h.whole, 'CURRENT_SHA', hashlib.sha256(s4).hexdigest())
    monkeypatch.setattr(h, 'CURRENT_SHA', hashlib.sha256(current).hexdigest())
    args = SimpleNamespace(**{n:tmp_path/n for n in ('prereg','lock','s3_snapshot','s3_snapshot_lock','s4_snapshot','s4_snapshot_lock')})
    for document, lock, data in ((args.prereg,args.lock,current),(args.s4_snapshot,args.s4_snapshot_lock,s4),
                                 (args.s3_snapshot,args.s3_snapshot_lock,s3)):
        document.write_bytes(data)
        lock.write_text(hashlib.sha256(data).hexdigest())
    h.verify_locks(args)
    getattr(args,field).write_bytes(b'changed')
    with pytest.raises(ValueError, match='hash mismatch'):
        h.verify_locks(args)


def test_start_checks_frozen_code_before_any_rebuild(tmp_path, monkeypatch):
    args = SimpleNamespace(s4=tmp_path, s3_snapshot=None, s3_snapshot_lock=None, s4_snapshot=None, s4_snapshot_lock=None)
    monkeypatch.setattr(h, 'verify_locks', lambda a:None)
    monkeypatch.setattr(w, 'verify_inputs', lambda a:None)
    monkeypatch.setattr(h, 'S4_RECORDS', {})
    (tmp_path/'code_hash.txt').write_text('wrong  labels/rules_v3.py\n')
    with pytest.raises(ValueError, match='frozen code hash'):
        h.verify_inputs(args)


@pytest.mark.parametrize('change', ['value','null','column','row','duplicate'])
def test_exact_fails_closed(change):
    a = pd.DataFrame(dict(cohort=['old','old'], player_id=['x','x'], game_id=['a','b'], color='white', value=[1.,np.nan]))
    b = a.copy()
    if change == 'value': b.loc[0,'value'] += np.finfo(float).eps
    elif change == 'null': b.loc[1,'value'] = 0.
    elif change == 'column': b['extra']=1
    elif change == 'row': b=b.iloc[:1]
    else: b=pd.concat([b,b.iloc[[0]]])
    assert h.exact(a,a)['max_abs_diff']==0.
    with pytest.raises(ValueError):h.exact(a,b)


def test_prediction_scope_every_column_accounted_for():
    predicted = score_fixture()
    excluded = [f'{c}::{head}::calibrated' for c in t.FITTED for head in
                (('whole','composite') if c=='P3-B/v3' else ('pre','p20','composite'))]
    compared, omissions = h.prediction_scope([*predicted, *excluded])
    assert set(compared)==set(predicted) and set(omissions)==set(excluded)
    assert not set(compared)&set(omissions)
    for cols in ([*compared,*omissions,'mystery'], compared, [*compared[:-1],*omissions]):
        with pytest.raises(ValueError):h.prediction_scope(cols)


@pytest.mark.parametrize('assignment', h.PARTS)
def test_holdouts_reach_unchanged_frozen_functions_and_restore_parts(monkeypatch, assignment):
    games,moves=history_fixture()
    games.loc[10:,'assignment']=assignment
    targets=games.iloc[10:].copy().assign(part=assignment)
    seen=[]
    original=p.build_player
    def checked(g,m,t,*args,**kw):
        assert t.assignment.eq('development').all() and t.part.eq('train').all()
        assert set(t.game_id)==set(targets.game_id)
        assert g.assignment.eq('development').all() # full history usable in S5
        seen.append(args[0])
        return original(g,m,t,*args,**kw)
    monkeypatch.setattr(p,'build_player',checked)
    result=h.player_tables(games,moves,targets,True)
    assert seen==['labels','features']
    for table in result[:3]:
        assert table.part.eq(assignment).all() and set(table.game_id)==set(targets.game_id)
    assert result[-1]['targets']==len(targets)


def test_build_target_selection_never_includes_development_or_drops():
    g,_=history_fixture()
    g.loc[0,'assignment']='A_prime'
    g.loc[1,'assignment']='B_prime'
    g.loc[2,'assignment']='drop_shared_development'
    targets=h.select_targets(g,True)
    assert targets.game_id.tolist()==g.game_id.iloc[:2].tolist()
    assert targets.part.tolist()==list(h.PARTS)
    with pytest.raises(ValueError,match='wrong phase'):
        h.player_tables(g,pd.DataFrame(),g.iloc[[3]],True)


def test_incomplete_prefix_drop_and_both_colours_stop():
    g,m=history_fixture()
    g['assignment']='A_prime'
    target=g.iloc[[12]].assign(part='A_prime')
    incomplete=m[~(m.game_id.eq(g.game_id[12])&m.color.eq('black'))]
    labels,pre,p20,drops,audit=h.player_tables(g,incomplete,target,True)
    assert len(labels)==len(drops)==1 and pre.empty and p20.empty
    assert drops.part.tolist()==['A_prime']
    with pytest.raises(ValueError,match='unhandled incomplete'):
        h.player_tables(g,m[~(m.game_id.eq(g.game_id[12])&m.ply.eq(20))],target,True)
    inventory=pd.DataFrame([dict(zip(h.KEYS,['old','fixture-player',g.game_id[12],'white']),color_present='black')])
    with pytest.raises(ValueError,match='own-colour'):
        p.check_own_colour(inventory,labels.assign(label='TILT'))


def test_no_fit_or_calibration_and_abstain_scored(monkeypatch):
    def forbidden(*a,**kw):raise AssertionError('S5 must never fit')
    from tilt.core import train as core_train
    for module,name in ((t,'fit_head'),(t,'fit_all'),(t,'calibrations'),(t,'calibrate'),(core_train,'calibrate'),(t.phase5.Fitted,'fit')):
        monkeypatch.setattr(module,name,forbidden)
    pred=score_fixture()
    assert pred.label.eq('ABSTAIN').any()
    assert np.isfinite(pred['M-v3::composite::frozen']).all()
    assert not any(c.endswith('::calibrated') and c.split('::')[0] in t.FITTED for c in pred)


def test_composite_null_result_fill_and_isolation():
    tables,reg,bundles,deployed=scored_fixture()
    tables[0].loc[0,'result_score']=np.nan
    original=tables[1].copy()
    result=h.score_tables(*tables,reg,bundles,deployed)
    assert result['B-result::composite::calibrated'].iloc[0]==.5
    pd.testing.assert_frame_equal(tables[1],original)
    for c in t.FITTED:
        if c=='P3-B/v3':continue
        pre=result[f'{c}::pre::frozen']
        p20=result[f'{c}::p20::frozen']
        np.testing.assert_equal(result[f'{c}::composite::frozen'],np.where(result.plies.ge(20),p20,pre))
    changed=list(tables)
    changed[3]=changed[3].copy()
    changed[3][list(w.WHOLE_ONLY)]=999
    other=h.score_tables(*changed,reg,bundles,deployed)
    for c in result:
        if c.split('::')[0] in ('M-v3','M-v3-ns','B-skill','P3-B@20/v3','P3-B@20 frozen'):
            np.testing.assert_equal(result[c].to_numpy(),other[c].to_numpy())


def test_stratum_bootstrap_clustered_paired_and_skip_counts():
    players=np.array(['positive','positive','negative','negative'])
    y=np.array([1.,1.,0.,0.])
    scores={'M-v3':np.array([.8,.9,.1,.2]),'B':np.array([.2,.1,.9,.8])}
    a=t.bootstrap(players,y,scores,[('M-v3','B')])
    b=t.bootstrap(players,y,scores,[('M-v3','B')])
    assert a==b and a['skipped']==a['no_positive']+a['one_class']
    rng=np.random.default_rng(42)
    draws=[rng.integers(0,2,2) for _ in range(1000)]
    assert a['skipped']==sum(len(set(d))==1 for d in draws)
    assert a['no_positive']>0 and a['one_class']>0
    assert a['paired']['M-v3-B']['ci'][0]>0


@pytest.mark.parametrize('failure', ['tilt','skip','zero','negative','missing','ece'])
def test_one_failing_cell_prevents_adoption(failure):
    metrics,boot=good_decision()
    assert h.adoption(metrics,boot)['adopted']
    cell=boot['B_prime']['lt40']['B-skill']
    if failure=='tilt':cell['tilt']=29
    elif failure=='skip':cell['skipped']=101
    elif failure=='zero':cell['ci'][0]=0.
    elif failure=='negative':cell['ci'][0]=-.01
    elif failure=='missing':cell['ci']=None
    else:metrics['parts']['B_prime']['all']['M-v3::composite']['ece']=.050001
    result=h.adoption(metrics,boot)
    assert not result['adopted'] and result['verdict']=='not adopted'
    assert len(result['deciding_cells'])==16
    assert sum(not c['met'] for c in result['deciding_cells']+result['calibration'])==1


def test_estimability_boundaries_and_all_games_do_not_decide():
    metrics,boot=good_decision()
    boot['pooled']={'all':{'irrelevant':'fails'}}
    assert h.adoption(metrics,boot)['adopted']
    metrics['parts']['A_prime']['all']['M-v3::composite']['ece']=None
    assert not h.adoption(metrics,boot)['adopted']


def synthetic_premetric():
    tables,reg,bundles,deployed=scored_fixture()
    labels,pre,p20,whole=tables
    drops=pd.DataFrame(columns=p.EXCLUSION_COLS)
    audit=dict(targets=len(pre),true_overlap=0,upper_overlap=40)
    return (*tables,drops),audit


@pytest.mark.parametrize('failure', ['count','drop','overlap','label','pre','p20','whole','duplicate','part','manifest'])
def test_every_premetric_guard_stops(monkeypatch,failure):
    tables,audit=synthetic_premetric()
    tables=list(tables)
    monkeypatch.setattr(h,'TARGET_COUNTS',tables[1].groupby('part').size().to_dict())
    monkeypatch.setattr(h,'DROP_COUNTS',dict(A_prime=0,B_prime=0))
    manifest=tables[0][h.KEYS+['part']].rename(columns={'part':'assignment'})
    h.premetric(tables,audit,manifest)
    if failure=='count':h.TARGET_COUNTS['A_prime']+=1
    elif failure=='drop':h.DROP_COUNTS['A_prime']=1
    elif failure=='overlap':audit['true_overlap']=3
    elif failure=='label':tables[0]=tables[0].iloc[1:]
    elif failure=='pre':tables[1]=tables[1].iloc[1:]
    elif failure=='p20':tables[2]=tables[2].iloc[1:]
    elif failure=='whole':tables[3]=tables[3].iloc[1:]
    elif failure=='duplicate':tables[0]=pd.concat([tables[0],tables[0].iloc[[0]]])
    elif failure=='part':tables[2]=tables[2].assign(part='wrong')
    else:manifest=manifest.iloc[1:]
    with pytest.raises(ValueError):h.premetric(tables,audit,manifest)


def test_metrics_all_strata_heads_references_and_abstain_exclusion():
    pred=score_fixture()
    metrics,boot,lengths=h.reports(pred)
    labelled=pred[pred.label.ne('ABSTAIN')]
    for part in (*h.PARTS,'pooled'):
        assert set(boot[part])==set(t.STRATA)
        for s in t.STRATA:
            data=labelled if part=='pooled' else labelled[labelled.part.eq(part)]
            data=data.loc[t.stratum(data,s)]
            count=metrics['counts'][part]['strata'][s]
            assert count['labelled']==len(data) and count['tilt']==int(data.label.eq('TILT').sum())
            assert set(boot[part][s])==set((*t.FITTED,*t.UNFITTED))-{'M-v3'}
            assert 'M-v3::pre' in metrics['parts'][part][s] and 'M-v3::p20' in metrics['parts'][part][s]
            assert 'ece' not in metrics['parts'][part][s]['R-pre::composite']
        assert set(lengths[part])==set((*t.FITTED,*t.UNFITTED))
    # Altering ABSTAIN scores changes no metric or interval.
    changed=pred.copy()
    changed.loc[changed.label.eq('ABSTAIN'),h.metric_columns(changed)]=.123
    assert h.reports(changed)==(metrics,boot,lengths)


def publish_synthetic_run(out, predictions, reports):
    out.mkdir()
    # All required output files, with deterministic synthetic contents. The
    # actual build/scoring paths are exercised separately above and below.
    for name in h.RUN_FILES:
        if name=='verify.json':continue
        if name=='equivalence.json':h.write_json(out/name,dict(passed=True,complete=True))
        elif name=='predictions_holdout.parquet':predictions.to_parquet(out/name,index=False)
        elif name in h.METRIC_FILES:h.write_json(out/name,reports[h.METRIC_FILES.index(name)])
        else:(out/name).write_bytes(b'synthetic fixture\n')
    h.write_json(out/'verify.json',dict(artifacts={n:split_v3.sha(out/n) for n in h.RUN_FILES if n!='verify.json'}))


def test_two_synthetic_score_and_evaluate_runs_identical_and_compare(tmp_path):
    a,b=score_fixture(),score_fixture()
    pd.testing.assert_frame_equal(a,b,check_exact=True)
    reports=h.reports(a)
    for n,f in [('run1',a),('run2',b)]:publish_synthetic_run(tmp_path/n,f,reports)
    result=h.compare(tmp_path/'run1',tmp_path/'run2',tmp_path/'determinism.json',tmp_path/'adoption.json')
    assert h.read_json(tmp_path/'determinism.json')['passed']
    assert (tmp_path/'adoption.json').exists() and result==h.adoption(*reports[:2])
    with pytest.raises(FileExistsError):h.compare(tmp_path/'run1',tmp_path/'run2',tmp_path/'determinism.json',tmp_path/'adoption.json')


def test_compare_difference_withholds_adoption(tmp_path):
    pred=score_fixture()
    reports=h.reports(pred)
    for n in ('run1','run2'):publish_synthetic_run(tmp_path/n,pred,reports)
    target=tmp_path/'run2'/h.METRIC_FILES[2]
    target.write_text(target.read_text()+'\n')
    record=h.read_json(tmp_path/'run2/verify.json')
    record['artifacts'][target.name]=split_v3.sha(target)
    h.write_json(tmp_path/'run2/verify.json',record)
    with pytest.raises(ValueError,match='two runs differ'):
        h.compare(tmp_path/'run1',tmp_path/'run2',tmp_path/'determinism.json',tmp_path/'adoption.json')
    assert not (tmp_path/'adoption.json').exists()


def test_smoke_cannot_unlock_build_and_phases_require_evidence(tmp_path,monkeypatch):
    args=SimpleNamespace(phase='build',out=tmp_path)
    monkeypatch.setattr(h,'destination',lambda a:None)
    monkeypatch.setattr(h,'witness',lambda *a,**kw:dict())
    h.write_json(tmp_path/'equivalence.json',dict(passed=True,complete=False))
    monkeypatch.setattr(h.split,'load_headers',lambda *a:pytest.fail('holdout opened'))
    with pytest.raises(ValueError,match='full equivalence'):h.run_phase(args)


def test_witness_detects_input_and_artifact_changes(tmp_path,monkeypatch):
    now=dict(passed=True,inputs={'source':'frozen'},artifacts={})
    monkeypatch.setattr(h,'verify_inputs',lambda a:deepcopy(now))
    args=SimpleNamespace(out=tmp_path)
    h.write_json(tmp_path/'verify.json',now)
    h.witness(args)
    (tmp_path/'equivalence.json').write_text('original')
    h.seal(args,['equivalence.json'])
    h.witness(args,'equivalence.json')
    (tmp_path/'equivalence.json').write_text('changed')
    with pytest.raises(ValueError,match='artifact changed'):h.witness(args)
    now['inputs']['source']='changed'
    with pytest.raises(ValueError,match='inputs changed'):h.witness(args)


def make_cli_fixture(base):
    """Tiny committed parquet roots; actual frozen move and whole-game workers."""
    import sqlite3
    root=base/'root'
    (root/'features').mkdir(parents=True)
    (root/'normalized/games').mkdir(parents=True)
    with sqlite3.connect(root/'index.sqlite') as db:
        db.execute('create table batches(batch text)')
        db.execute("insert into batches values ('fixture')")
    gs,ms=[],[]
    for i in range(3):
        g,m=history_fixture(n=8)
        g['cohort']='new'
        g['player']=f'synthetic-{i}'
        g['player_id']=h.public(f'synthetic-{i}')
        g['raw_game_id']=g.game_id+f'-{i}'
        g['game_id']=g.raw_game_id.map(lambda v:h.public(v,'game:'))
        m['game_id']=m.game_id+f'-{i}'
        m.loc[m.color.eq('white'),'player']=f'synthetic-{i}'
        if i==0:
            g['assignment']='A_prime'
            g['part']=None
        elif i==1:
            g.loc[2:,'assignment']='B_prime'
            g.loc[2:,'part']=None
        gs.append(g);ms.append(m)
    # Crash geometry: history of a development player shares the physical
    # game of a B-prime player who also has development targets.
    shared=gs[2].iloc[[-1]].copy()
    shared['raw_game_id']=gs[1].iloc[-1].raw_game_id
    shared['game_id']=gs[1].iloc[-1].game_id
    shared['color']='black'
    shared['assignment']='drop_shared_development'
    shared['part']=None
    gs[2]=pd.concat([gs[2].iloc[:-1],shared],ignore_index=True)
    # Match the physical game's ratings; only its boundary side is read.
    gs[1].loc[7,'color']='white'
    games=pd.concat(gs,ignore_index=True)
    moves=pd.concat(ms,ignore_index=True)
    moves=moves[moves.game_id.ne('fixture-game-007-2')]
    moves.loc[moves.game_id.eq(shared.raw_game_id.iloc[0]) & moves.color.eq('black'),'player']='synthetic-2'
    games.to_parquet(base/'hold.parquet',index=False)
    stored=games.drop(columns=['raw_game_id','player_id','cohort','assignment','part']).copy()
    stored['game_id']=games.raw_game_id
    for c in w.FEATURES:
        if c not in stored:stored[c]=.15
    stored.to_parquet(root/'features/games.parquet',index=False)
    moves.to_parquet(root/'features/moves.parquet',index=False)
    raw=games.drop_duplicates('raw_game_id').copy()
    raw['game_id']=raw.raw_game_id
    raw['rated']=True
    raw['white_rating']=raw.rating
    raw['black_rating']=raw.opponent_rating
    raw[['game_id','status','plies','rated','initial_seconds','increment_seconds','white_rating','black_rating']].to_parquet(
        root/'normalized/games/fixture.parquet',index=False)
    refs=base/'refs'
    refs.mkdir()
    p.registry().to_csv(refs/'feature_registry.csv',index=False)
    games.assign(split_key=games.player.map(lambda v:split_v3.digest('label-v3-dev-split-1:'+v)))[h.KEYS+['part','split_key']].to_parquet(refs/'dev_split_manifest.parquet',index=False)
    games[h.KEYS+['assignment']].to_parquet(refs/'holdout_manifest.parquet',index=False)
    args=SimpleNamespace(old_root=root,new_root=root,s2=refs,s3=refs,processes=1,players=0)
    wanted=games[games.part.isin(split_v3.PARTS)]
    headers=h.development_headers(args,wanted)
    assert headers.assignment.eq('B_prime').sum()==6
    result=h.rebuild(args,headers,h.select_targets(headers,False),False)
    for name,table in zip(('labels_dev.parquet','features_pre.parquet','features_p20.parquet','features_p3b_whole.parquet'),result[:4]):
        table.to_parquet(refs/name,index=False)
    result[4].to_csv(refs/'excluded_incomplete_moves.csv',index=False)
    pred=synthetic_load_scores(args,result[:4])
    for c in t.FITTED:
        for head in (('whole','composite') if c=='P3-B/v3' else ('pre','p20','composite')):
            pred[f'{c}::{head}::calibrated']=-999.
    pred.to_parquet(refs/'predictions.parquet',index=False)


def synthetic_load_scores(args,tables):
    labels,pre,p20,whole=tables
    reg=p.registry()
    combined=h.adapt(pre).merge(h.adapt(p20),on=h.KEYS+['part'])
    bundles={}
    for c in t.FITTED:
        bundles[c]=dict(heads={head:bundle(w.FEATURES if head=='whole' else
            t.matrix(combined if head=='p20' else h.adapt(pre),head,c,reg).columns)
            for head in (('whole',) if c=='P3-B/v3' else ('pre','p20'))})
    return h.score_tables(*tables,reg,bundles,bundle(w.FEATURES))


def synthetic_cli(base,argv):
    """Test-only IO seams; production CLI offers no bypass or synthetic switch."""
    h.verify_inputs=lambda args:dict(passed=True,inputs={'fixture':'synthetic'},artifacts={})
    h.split.load_headers=lambda *args:pd.read_parquet(base/'hold.parquet')
    h.load_scores=synthetic_load_scores
    h.TARGET_COUNTS=dict(A_prime=8,B_prime=6)
    h.DROP_COUNTS=dict(A_prime=0,B_prime=0)
    h.main(argv)


def test_all_cli_phases_fresh_processes_and_parallelism(tmp_path):
    import os,subprocess,sys
    make_cli_fixture(tmp_path)
    driver=tmp_path/'driver.py'
    driver.write_text('from pathlib import Path\nimport sys\nfrom test_v3_holdout import synthetic_cli\n'
                      'if __name__ == "__main__":\n    synthetic_cli(Path(sys.argv[1]),sys.argv[2:])\n')
    common=[]
    for name in ('old-root','new-root','s1','s2','s3','s4','prereg','lock','s3-snapshot','s3-snapshot-lock',
                 's4-snapshot','s4-snapshot-lock','bundles','deployment-pointer','deployed-bundle'):
        path=tmp_path/'root' if name in ('old-root','new-root') else tmp_path/'refs'
        if name=='deployed-bundle':path=path/'bundle.joblib'
        common+=['--'+name,str(path)]
    env=dict(os.environ)
    env['PYTHONPATH']=os.pathsep.join([str(Path(__file__).parent),str(Path(h.__file__).resolve().parents[2]),env.get('PYTHONPATH','')])
    for run,processes in (('run1',1),('run2',2)):
        for phase in ('verify','equivalence','build','score','evaluate'):
            result=subprocess.run([sys.executable,str(driver),str(tmp_path),phase,*common,'--out',str(tmp_path/run),
                            '--processes',str(processes)],env=env,capture_output=True,text=True)
            assert result.returncode==0, result.stderr
    subprocess.run([sys.executable,str(driver),str(tmp_path),'compare',*common,'--out',str(tmp_path/'final'),
                    '--run1',str(tmp_path/'run1'),'--run2',str(tmp_path/'run2'),
                    '--determinism',str(tmp_path/'determinism.json'),'--adoption',str(tmp_path/'adoption.json')],
                   env=env,check=True,capture_output=True,text=True)
    assert h.read_json(tmp_path/'determinism.json')['passed']
    eq=h.read_json(tmp_path/'run1/equivalence.json')
    assert eq['complete'] and eq['headers']['boundary_rows']==6
    assert eq['headers']['shared_games']==1
    assert all(eq['headers']['assertions'].values())
    assert h.read_json(tmp_path/'adoption.json')['verdict']=='not adopted'
    assert h.read_json(tmp_path/'run1/metrics_holdout.json')['incomplete_prefix_drops']==dict(A_prime=0,B_prime=0)
    assert {f.name for f in (tmp_path/'run1').iterdir()}==set(h.RUN_FILES)


def shared_header_fixture(tmp_path, left='drop_shared_development', right='B_prime', cohort='new'):
    """Both players have dev targets; shared sides carry adversarial values."""
    root=tmp_path/'root'
    (root/'features').mkdir(parents=True)
    (root/'out').mkdir()
    refs=tmp_path/'refs'
    refs.mkdir()
    gs=[]
    for i,assignment in enumerate((left,right)):
        g,_=history_fixture(n=2)
        g['cohort']=cohort
        g['player']=f'pair-{i}'
        g['player_id']=g.player.map(h.public)
        g['raw_game_id']=[f'dev-{i}','shared']
        g['game_id']=g.raw_game_id.map(lambda v:h.public(v,'game:'))
        g['color']='white' if i==0 else 'black'
        g.loc[1,'assignment']=assignment
        g.loc[1,'part']=None if assignment!='development' else 'train'
        gs.append(g)
    games=pd.concat(gs,ignore_index=True)
    stored=games.drop(columns=['cohort','player_id','raw_game_id','part','assignment']).copy()
    stored['game_id']=games.raw_game_id
    stored.to_parquet(root/'features/games.parquet',index=False)
    games[h.KEYS+['assignment']].to_parquet(refs/'holdout_manifest.parquet',index=False)
    wanted=games[games.part.isin(split_v3.PARTS)].copy()
    wanted['split_key']=wanted.player.map(lambda v:split_v3.digest('label-v3-dev-split-1:'+v))
    wanted[h.KEYS+['part','split_key']].to_parquet(refs/'dev_split_manifest.parquet',index=False)
    games[['player_id','game_id',*rules_v3.BRIDGE]].to_parquet(root/'out/weak_by_player.parquet',index=False)
    args=SimpleNamespace(old_root=root,new_root=root,s2=refs,s3=refs,players=0)
    return args,games,wanted


@pytest.mark.parametrize('left,right,cohort', [
    ('drop_shared_development','B_prime','new'),
    ('B_prime','B_prime','new'),
    ('A_prime','B_prime','new'),
    ('A_prime','development','new'),
    ('drop_shared_development','development','old'),
    ('drop_shared_development','development','new'),
])
def test_shared_headers_exact_sides_and_build_targets(tmp_path,monkeypatch,left,right,cohort):
    args,allgames,wanted=shared_header_fixture(tmp_path,left,right,cohort)
    monkeypatch.setattr(w,'raw_projection',lambda root,physical,columns:allgames.rename(
        columns={'game_id':'export_id','raw_game_id':'game_id'}).drop_duplicates('game_id').assign(
            rated=True,white_rating=1800,black_rating=1800)[['game_id',*columns]])
    original=pd.read_parquet
    holdkeys=h.side_set(allgames[allgames.assignment.isin(h.PARTS)].rename(
        columns={'game_id':'export_id','raw_game_id':'game_id'}))
    reads=[]
    def guarded(path,*a,**kw):
        out=original(path,*a,**kw)
        if Path(path)==args.new_root/'features/games.parquet':
            columns=kw['columns']
            if set(columns)-set(h.RAW_KEYS):
                selected=h.side_set(out)
                reads.append((columns,selected))
                if selected & holdkeys:
                    assert set(columns)<=set(h.RAW_KEYS+['start_ms','session_id'])
                    assert not any(k in selected for k in h.side_set(allgames[allgames.assignment.eq('A_prime')].rename(
                        columns={'game_id':'export_id','raw_game_id':'game_id'})))
        return out
    monkeypatch.setattr(pd,'read_parquet',guarded)
    monkeypatch.setattr(split_v3,'load_headers',lambda *a:pytest.fail('frozen loader called during equivalence'))
    headers=h.development_headers(args,wanted)
    expected=allgames[~allgames.assignment.isin(h.PARTS)]
    edges=allgames[allgames.assignment.eq('B_prime')]
    assert all(h.assert_headers(headers,expected,edges).values())
    assert not headers.assignment.eq('A_prime').any()
    assert len(headers)==len(expected)+len(edges)
    assert reads
    if left=='drop_shared_development':
        assert h.whole.keyset(allgames[allgames.assignment.eq(left)])<=h.whole.keyset(headers)
    targets=h.select_targets(allgames,True) if allgames.assignment.isin(h.PARTS).any() else None
    if targets is not None:
        assert h.whole.keyset(targets)==h.whole.keyset(allgames[allgames.assignment.isin(h.PARTS)])
        assert not targets.assignment.isin(['development','drop_shared_development']).any()


@pytest.mark.parametrize('failure', ['duplicate','A_prime','B_value','B_not_boundary','missing_nonholdout'])
def test_four_header_assertions_stop_under_section8(tmp_path,failure):
    args,g,wanted=shared_header_fixture(tmp_path)
    expected=g[~g.assignment.isin(h.PARTS)]
    boundary=g[g.assignment.eq('B_prime')][h.KEYS+['assignment','start_ms','session_id']]
    headers=pd.concat([expected,boundary],ignore_index=True)
    if failure=='duplicate':headers=pd.concat([headers,headers.iloc[[0]]])
    elif failure=='A_prime':headers.loc[0,'assignment']='A_prime'
    elif failure=='B_value':headers.loc[headers.assignment.eq('B_prime'),'rating']=999
    elif failure=='B_not_boundary':boundary=boundary.iloc[:0]
    else:headers=headers.iloc[1:]
    with pytest.raises(ValueError,match='S5 section 8 stop: headers:'):
        h.assert_headers(headers,expected,boundary)


def test_boundary_reader_stops_if_cross_product_returns_another_player(tmp_path,monkeypatch):
    args,g,wanted=shared_header_fixture(tmp_path)
    plan=h.header_plan(args,wanted)['new']
    original=pd.read_parquet
    def cross_product(path,*a,**kw):
        return original(path,columns=kw['columns'],filters=[('game_id','==','shared')])
    monkeypatch.setattr(pd,'read_parquet',cross_product)
    with pytest.raises(ValueError,match='section 8 stop: boundary read: another player'):
        h.read_sides(plan[0],plan[3],h.RAW_KEYS+['start_ms','session_id'],boundary=True)


def test_old_cross_product_reader_fails_new_assertions(tmp_path):
    args,g,wanted=shared_header_fixture(tmp_path)
    root,keys,readable,boundary=h.header_plan(args,wanted)['new']
    # Reference of the crashed reader, deliberately retained only in tests.
    def old_reader(sides,columns):
        return pd.read_parquet(root/'features/games.parquet',columns=columns,
            filters=[('player','in',keys.player.unique().tolist()),('game_id','in',sides.game_id.unique().tolist())])
    values=old_reader(readable,[*h.RAW_KEYS,'rating'])
    assert h.side_set(values) & h.side_set(boundary)
    edges=old_reader(boundary,h.RAW_KEYS+['start_ms','session_id']).assign(assignment='B_prime')
    values=values.merge(keys[h.RAW_KEYS+['assignment']],on=h.RAW_KEYS)
    bad=pd.concat([values,edges],ignore_index=True)
    bad['cohort']='new'
    bad['player_id']=bad.player.map(h.public)
    bad['game_id']=bad.game_id.map(lambda v:h.public(v,'game:'))
    with pytest.raises(ValueError,match='section 8 stop: headers: duplicate'):
        h.assert_headers(bad,g[~g.assignment.isin(h.PARTS)],g[g.assignment.eq('B_prime')])


def test_header_plan_entry_reads_keys_only(tmp_path,monkeypatch):
    args,g,wanted=shared_header_fixture(tmp_path)
    original=pd.read_parquet
    def guarded(path,*a,**kw):
        allowed=h.RAW_KEYS if Path(path).name=='games.parquet' else h.KEYS+['part','assignment','split_key']
        assert set(kw['columns'])<=set(allowed)
        return original(path,*a,**kw)
    monkeypatch.setattr(pd,'read_parquet',guarded)
    result=h.check_header_plan(args)
    assert result['passed'] and result['value_columns_read']==0
    assert result['E8_3_B_prime_sides_in_old_value_read']==1
    assert result['cohorts']['new']['value_sides']==3
    assert result['cohorts']['new']['boundary_sides']==1


@pytest.mark.parametrize('failure',['duplicate','missing','incomplete_count','none'])
def test_build_precomputation_guards(tmp_path,monkeypatch,failure):
    args,g,wanted=shared_header_fixture(tmp_path)
    _,moves=history_fixture(n=3)
    ids=dict(zip(moves.game_id.unique(),['dev-0','dev-1','shared']))
    moves['game_id']=moves.game_id.map(ids)
    if failure=='incomplete_count':
        moves=moves[~(moves.game_id.eq('shared') & moves.color.eq('black'))]
    moves.to_parquet(args.new_root/'features/moves.parquet',index=False)
    manifest=g[h.KEYS+['assignment']].copy()
    monkeypatch.setattr(h,'DROP_COUNTS',dict(A_prime=0,B_prime=0))
    if failure=='duplicate':g=pd.concat([g,g.iloc[[0]]])
    elif failure=='missing':manifest=manifest[~manifest.assignment.eq('B_prime')]
    if failure=='none':
        assert h.build_targets(args,g,manifest).assignment.eq('B_prime').all()
    else:
        with pytest.raises(ValueError,match='(section 8 stop: build:|incomplete-target count stop)'):
            h.build_targets(args,g,manifest)


def test_boundary_assignment_from_manifest_must_be_B_prime(tmp_path,monkeypatch):
    args,g,wanted=shared_header_fixture(tmp_path)
    plans=h.header_plan(args,wanted)
    root,keys,values,edges=plans['new']
    plans['new']=(root,keys,values,pd.concat([edges,values.iloc[[0]]]))
    monkeypatch.setattr(h,'header_plan',lambda *a:plans)
    monkeypatch.setattr(w,'raw_projection',lambda root,physical,columns:g.rename(
        columns={'game_id':'export_id','raw_game_id':'game_id'}).drop_duplicates('game_id').assign(
            rated=True,white_rating=1800,black_rating=1800)[['game_id',*columns]])
    with pytest.raises(ValueError,match='section 8 stop: boundary read: assignment is not B_prime'):
        h.development_headers(args,wanted)


@pytest.mark.parametrize('source',['stored','holdout_manifest','dev_split_manifest'])
def test_key_plan_duplicate_input_stops(tmp_path,source):
    args,g,wanted=shared_header_fixture(tmp_path)
    path=args.new_root/'features/games.parquet' if source=='stored' else args.s2/(source+'.parquet')
    frame=pd.read_parquet(path)
    pd.concat([frame,frame.iloc[[0]]]).to_parquet(path,index=False)
    with pytest.raises(ValueError,match='section 8 stop: header plan: duplicate'):
        h.check_header_plan(args)


def test_old_key_plan_uses_S3_player_key_not_sparse_S2_membership(tmp_path,monkeypatch):
    args,g,wanted=shared_header_fixture(tmp_path,'drop_shared_development','development','old')
    # S2 records only shared old sides. Ordinary old identities are legacy
    # export pseudonyms; S3's deterministic split key bridges raw usernames.
    manifest=g[g.assignment.eq('drop_shared_development')][h.KEYS+['assignment']]
    manifest.to_parquet(args.s2/'holdout_manifest.parquet',index=False)
    wanted['player_id']='legacy-'+wanted.player_id
    wanted[h.KEYS+['part','split_key']].to_parquet(args.s3/'dev_split_manifest.parquet',index=False)
    path=args.old_root/'features/games.parquet'
    stored=pd.read_parquet(path)
    extra=stored.iloc[[0]].assign(player='unrelated-player')
    pd.concat([stored,extra],ignore_index=True).to_parquet(path,index=False)
    original=pd.read_parquet
    def keys_only(path,*a,**kw):
        allowed=h.RAW_KEYS if Path(path).name=='games.parquet' else h.KEYS+['part','assignment','split_key']
        assert set(kw['columns'])<=set(allowed)
        return original(path,*a,**kw)
    monkeypatch.setattr(pd,'read_parquet',keys_only)
    result=h.check_header_plan(args)
    assert result['cohorts']['old']['development_players']==2
    assert result['cohorts']['old']['stored_sides']==4
    assert result['cohorts']['old']['sides_per_assignment']==dict(development=3,drop_shared_development=1)
