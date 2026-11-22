"""S4.9 synthetic-only fitting, calibration, isolation and determinism."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
import pytest

from tilt.training import distill as t
from tilt.evaluation import compare_p3b as p, model_fit
from tilt.features import prefix_features


def fixture():
    rng = np.random.default_rng(42)
    rows = []
    # Distinct synthetic players across calibration folds, with both classes and
    # all three lengths per player. ABSTAIN is deliberately easy to identify.
    for i in range(24):
        part = 'train' if i < 12 else ('V_A' if i < 18 else 'V_B')
        for j in range(18):
            rows.append(dict(cohort='old',player_id=f'synthetic-player-{i:02}',
                game_id=f'synthetic-game-{i:02}-{j:02}',color='white',part=part,
                label='ABSTAIN' if j==17 else ('TILT' if j%2 else 'NOT'),
                plies=[12,30,60][j%3],result_score=float(j%2)))
    meta = pd.DataFrame(rows)
    registry = prefix_features.registry()
    pre = meta[p.KEYS+['part']].copy()
    signal = meta.label.map({'TILT':2.,'NOT':-2.,'ABSTAIN':50.}).to_numpy()
    for c in registry.loc[registry.block.eq('pre'),'column']:
        pre[c] = signal + rng.normal(0,.1,len(meta))
    pre['losing_streak_before'] = (meta.label.eq('TILT')).astype(float)
    p20 = meta.loc[meta.plies.ge(20),p.KEYS+['part']].copy()
    for c in registry.loc[registry.block.eq('p20'),'column']:
        p20[c] = signal[meta.plies.ge(20)]+rng.normal(0,.1,len(p20))
    whole = meta[p.KEYS+['part']].copy()
    for c in p.FEATURES:
        whole[c] = signal+rng.normal(0,.1,len(meta))
    pre.loc[0,'prev_label']=np.nan
    pre['prev_E7']=np.nan  # keep_empty_features and indicator are exercised.
    return meta,pre,p20,registry,whole


def deployed_fixture(meta, whole):
    # Synthetic stand-in for the deployed artifact, never the actual bundle.
    y=meta.label.map({'NOT':0.,'TILT':1.}).to_numpy(float)
    rows=t.train_rows(meta)
    f=model_fit.Fitted(p.FEATURES,True,p.p3b_features.NO_INDICATOR,threads=2).fit(whole,y,rows)
    return dict(format='phase5',features=f.features,columns=f.columns,imputer=f.imputer,
        keep=f.keep,scaler=f.scaler,classifier=f.model,calibration=dict(model=None,status='synthetic'))


def test_registry_skill_subsets_and_whole_game_isolation():
    meta,pre,p20,reg,whole=fixture()
    combined=pre.merge(p20,on=p.KEYS+['part'],validate='one_to_one')
    expected={'rating'}|{'baseline_'+f+'_'+s for f in prefix_features.rules.FEATURES for s in ('median','mad')}
    assert set(t.skill_columns(reg))==expected and len(expected)==15
    for head,frame in [('pre',pre),('p20',combined)]:
        main=t.matrix(frame,head,'M-v3',reg)
        ns=t.matrix(frame,head,'M-v3-ns',reg)
        skill=t.matrix(frame,head,'B-skill',reg)
        assert set(main)-set(ns)==expected
        assert set(skill)==expected
        assert not set(main)&p.WHOLE_ONLY
        assert not set(t.matrix(frame,head,'P3-B@20/v3',reg))&p.WHOLE_ONLY
        for c in p.WHOLE_ONLY:
            with pytest.raises(ValueError):
                t.matrix(frame.assign(**{c:999.}),head,'M-v3',reg)
    with pytest.raises(ValueError):
        t.matrix(whole,'pre','M-v3',reg)
    assert not set(pre)&p.WHOLE_ONLY


def test_only_labelled_train_enters_every_preprocessor_and_classifier_fit(monkeypatch):
    meta,pre,_,reg,_=fixture()
    matrix=t.matrix(pre,'pre','M-v3',reg)
    expected=t.train_rows(meta)
    original=t.model_fit.Fitted.fit
    seen=[]
    def fit(self,frame,y,rows):
        assert len(frame)==len(expected)
        assert np.isfinite(y).all()
        pd.testing.assert_frame_equal(frame,matrix.iloc[expected])
        assert rows.tolist()==list(range(len(expected)))
        seen.append(True)
        return original(self,frame,y,rows)
    monkeypatch.setattr(t.model_fit.Fitted,'fit',fit)
    bundle,raw,cross,frozen,audit=t.fit_head(matrix,meta,'M-v3')
    assert seen==[True]
    assert len(raw)==len(meta) and np.isfinite(cross).all()
    assert bundle['imputer'].statistics_[0]<1 # ABSTAIN has signal 50.
    assert bundle['imputer'].keep_empty_features
    assert bundle['classifier'].get_params()['n_jobs']==2
    assert audit['frozen']['rows']==int((meta.part.ne('train')&meta.label.ne('ABSTAIN')).sum())


def test_cross_calibration_only_other_validation_fold_never_own_row(monkeypatch):
    meta,_,_,_,_=fixture()
    raw=np.arange(len(meta),dtype=float)/len(meta)
    calls=[]
    def calibration(prob,y):
        rows=np.rint(prob*len(meta)).astype(int)
        assert meta.iloc[rows].part.isin(['V_A','V_B']).all()
        assert meta.iloc[rows].label.isin(['TILT','NOT']).all()
        calls.append(rows)
        return dict(model=None,status=t.NORMAL)
    monkeypatch.setattr(t,'calibrate',calibration)
    cross,frozen,audit=t.calibrations(raw,meta)
    assert len(calls)==3
    assert set(calls[0])==set(np.flatnonzero(meta.part.ne('train')&meta.label.ne('ABSTAIN')))
    for held,source in enumerate(calls[1:]):
        assert all(t.fold(v)==1-held for v in meta.iloc[source].player_id)
        scored=np.flatnonzero(meta.part.ne('train')&meta.player_id.map(t.fold).eq(held))
        assert not set(source)&set(scored)
        assert set(meta.iloc[source].player_id).isdisjoint(set(meta.iloc[scored].player_id))
        assert audit['cross'][held]['held_fold']==held
    for player in meta.player_id.unique():
        expected=int(hashlib.sha256(('label-v3-cal-fold-1:'+player).encode()).hexdigest(),16)%2
        assert t.fold(player)==expected


def test_degenerate_calibration_status_and_positive_minimum():
    assert t.calibrate(np.full(30,.5),np.zeros(30,dtype=int))['status']!=t.NORMAL
    meta,pre,_,reg,_=fixture()
    meta.loc[meta.part.eq('train'),'label']='NOT'
    with pytest.raises(ValueError,match='50'):
        t.fit_head(t.matrix(pre,'pre','M-v3',reg),meta,'M-v3')
    with pytest.raises(ValueError,match='threads=2'):
        meta,pre,_,reg,_=fixture()
        t.fit_head(t.matrix(pre,'pre','M-v3',reg),meta,'M-v3',threads=3)


def test_composite_switches_at_twenty_only():
    assert t.composite([0,19,20,39,40],[.1]*5,[np.nan,np.nan,.8,.9,.7]).tolist()==[.1,.1,.8,.9,.7]
    with pytest.raises(ValueError,match='missing'):
        t.composite([20],[.1],[np.nan])


@pytest.mark.parametrize('part',['A_prime','B_prime','drop_shared_development','drop_shared_split','drop_incomplete_moves'])
def test_refusal_at_all_training_reporting_boundaries(tmp_path,part):
    meta,pre,p20,reg,whole=fixture()
    bad=meta.copy();bad.loc[0,'part']=part
    with pytest.raises(ValueError):t.train_rows(bad)
    with pytest.raises(ValueError):t.calibrations(np.full(len(bad),.5),bad)
    with pytest.raises(ValueError):t.fit_head(pre[['rating']],bad,'M-v3')
    with pytest.raises(ValueError):t.validate_tables(bad,pre,p20,reg,whole)
    with pytest.raises(ValueError):t.fit_all(bad,pre,p20,reg,whole,{},tmp_path,{})
    with pytest.raises(ValueError):t.report(bad,tmp_path)
    badpre=pre.copy();badpre.loc[0,'part']=part
    with pytest.raises(ValueError):t.matrix(badpre,'pre','M-v3',reg)


def test_population_and_part_changes_refused():
    meta,pre,p20,reg,whole=fixture()
    t.validate_tables(meta,pre,p20,reg,whole)
    with pytest.raises(ValueError,match='universe'):
        t.validate_tables(meta,pre.iloc[1:],p20,reg,whole)
    with pytest.raises(ValueError,match='population'):
        t.validate_tables(meta,pre,p20.iloc[1:],reg,whole)
    wrong=whole.copy();wrong.loc[0,'part']='V_A'
    with pytest.raises(ValueError,match='part'):
        t.validate_tables(meta,pre,p20,reg,wrong)


def test_clustered_paired_bootstrap_matches_phase5_seed42():
    players=np.repeat(['synthetic-a','synthetic-b','synthetic-c'],8)
    y=np.tile([0,1,0,0,1,1,0,1],3)
    scores={'a':np.linspace(.1,.9,24),'b':np.linspace(.9,.1,24)}
    result=t.bootstrap(players,y,scores,[('a','b')],1000,42)
    reference=model_fit.bootstrap(players,y,scores,np.ones(len(y),bool),[('a','b')],repetitions=1000,seed=42)
    assert result['ci']==reference['ci']['primary']
    assert result['paired']==reference['paired']['primary']
    assert result==t.bootstrap(players,y,scores,[('a','b')],1000,42)
    assert result['repetitions']==1000
    skipped=t.bootstrap(np.repeat(['synthetic-zero','synthetic-one'],4),np.repeat([0,1],4),
                        {'a':np.arange(8)/8},[],1000,42)
    assert skipped['no_positive']>0 and skipped['one_class']>0


def smoke(out):
    """Called in separate OS processes by the integration test and handoff smoke."""
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=2):
        meta,pre,p20,reg,whole=fixture()
        deployed=deployed_fixture(meta,whole)
        out=Path(out);out.mkdir(parents=True,exist_ok=True)
        whole.to_parquet(out/'features_p3b_whole.parquet',index=False)
        p.write_json(out/'p3b_parity.json',dict(passed=True,sample=False,synthetic=True))
        predictions=t.fit_all(meta,pre,p20,reg,whole,deployed,out,p.code_hashes())
        t.report(predictions,out)


def test_null_result_is_draw_only_for_b_result_with_identical_matrices_and_scores(tmp_path, monkeypatch):
    meta,pre,p20,reg,whole=fixture()
    meta.loc[1,'result_score']=0.5
    missing=meta.copy()
    missing.loc[[0,17,216,324],'result_score']=np.nan
    originals=[f.copy(deep=True) for f in (missing,pre,p20,reg,whole)]
    deployed=deployed_fixture(meta,whole)
    matrices=[]
    original=t.fit_head
    def fit(frame,hmeta,candidate,threads):
        matrices.append((candidate,frame.copy(deep=True)))
        return original(frame,hmeta,candidate,threads)
    monkeypatch.setattr(t,'fit_head',fit)
    results=[]
    for name,frame in [('known',meta),('missing',missing)]:
        out=tmp_path/name
        out.mkdir()
        whole.to_parquet(out/'features_p3b_whole.parquet',index=False)
        results.append(t.fit_all(frame,pre,p20,reg,whole,deployed,out,p.code_hashes()))
    known,actual=results
    score='B-result::composite::calibrated'
    null=actual.result_score.isna()
    assert null.sum()==4
    assert actual.loc[null,score].eq(0.5).all()
    np.testing.assert_array_equal(actual.loc[~null,score],1-actual.loc[~null,'result_score'])
    np.testing.assert_array_equal(known[score],1-known.result_score)
    # Only the B-result scores and the supplied result metadata may differ.
    pd.testing.assert_frame_equal(known.drop(columns=['result_score',score]),
                                  actual.drop(columns=['result_score',score]),check_exact=True)
    assert len(matrices)==18
    for (candidate,a),(other,b) in zip(matrices[:9],matrices[9:]):
        assert candidate==other
        pd.testing.assert_frame_equal(a,b,check_exact=True)
    for bundle in (tmp_path/'known/bundles').iterdir():
        assert bundle.read_bytes()==(tmp_path/'missing/bundles'/bundle.name).read_bytes()
    for before,after in zip(originals,(missing,pre,p20,reg,whole)):
        pd.testing.assert_frame_equal(before,after,check_exact=True)


@pytest.mark.parametrize('column,value',[
    ('ctx_context_rank',np.nan),('ctx_D',np.nan),
    ('losing_streak_before',np.nan),('plies',np.nan),('result_score',np.inf)])
def test_other_missing_reference_inputs_still_raise(tmp_path,monkeypatch,column,value):
    meta,pre,p20,reg,whole=fixture()
    (meta if column in meta else pre).loc[0,column]=value
    meta.loc[1,'result_score']=np.nan
    # Keep this focused on the real reference scoring and finiteness guard.
    def fit(frame,hmeta,candidate,threads):
        scores=np.full(len(hmeta),0.5)
        return {},scores,scores,scores,{}
    monkeypatch.setattr(t,'fit_head',fit)
    monkeypatch.setattr(t,'predict_bundle',lambda bundle,frame:(np.full(len(frame),0.5),))
    with pytest.raises(ValueError,match='Missing unfitted reference score'):
        t.fit_all(meta,pre,p20,reg,whole,{},tmp_path,{})


def test_synthetic_runs_in_separate_processes_identical_outputs(tmp_path):
    env=os.environ.copy()
    env['PYTHONPATH']=os.pathsep.join([str(Path(__file__).parent),str(Path(__file__).resolve().parents[2]/'src'),
                                     env.get('PYTHONPATH','')])
    command='import sys;from test_distill import smoke;smoke(sys.argv[1])'
    for run in ('run1','run2'):
        subprocess.run([sys.executable,'-c',command,str(tmp_path/run)],env=env,check=True,
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=600)
    result=t.compare(tmp_path/'run1',tmp_path/'run2',tmp_path/'determinism.json')
    assert result['passed'] and result['largest_absolute_prediction_difference']==0.
    bundle=joblib.load(tmp_path/'run1/bundles/M-v3.joblib')
    assert set(bundle['heads'])=={'pre','p20'}
    assert bundle['prereg_sha256']==p.CURRENT_SHA
    metrics=json.loads((tmp_path/'run1/metrics_validation.json').read_text())
    for part in t.PARTS:
        assert set(metrics['validation'][part])==set(t.STRATA)
        assert 'brier' not in metrics['validation'][part]['all']['R-pre::composite']
        assert 'brier' in metrics['validation'][part]['all']['M-v3::composite']
    # A tiny change must fail, with no nonzero tolerance allowed.
    changed=pd.read_parquet(tmp_path/'run2/predictions.parquet')
    col='M-v3::composite::calibrated';changed.loc[0,col]+=1e-12
    changed.to_parquet(tmp_path/'run2/predictions.parquet',index=False)
    assert not t.compare(tmp_path/'run1',tmp_path/'run2',tmp_path/'different.json')['passed']


def test_cli_all_steps_require_lock_and_paths():
    for step in ('p3b','train','report','gate','compare'):
        with pytest.raises(SystemExit):t.main([step])


@pytest.mark.parametrize('which',['V_A','V_B','ci','calibration','tests','determinism',None])
def test_gate_fails_closed_for_every_condition(tmp_path,monkeypatch,which):
    metrics={'validation':{part:{'all':{c+'::composite':{'pr_auc':ap}
        for c,ap in [('M-v3',.6),('R-pre',.2)]}} for part in ('V_A','V_B')}}
    if which in ('V_A','V_B'):metrics['validation'][which]['all']['M-v3::composite']['pr_auc']=.1
    boot={'pooled':{'all':{'paired':{'M-v3-R-pre':{'ci':[.1,.4]}}}}}
    if which=='ci':boot['pooled']['all']['paired']['M-v3-R-pre']['ci'][0]=0.
    audit={c:{head:{'frozen':{'status':t.NORMAL},'cross':[
        dict(status=t.NORMAL,held_fold=i,source_fold=1-i) for i in (0,1)]} for head in heads}
        for c,heads in {'M-v3':('pre','p20'),'P3-B/v3':('whole',),'B-skill':('pre','p20')}.items()}
    if which=='calibration':audit['B-skill']['pre']['cross'][0]['status']='identity: synthetic'
    evidence=dict(passed=True,s3_leakage_passed=True,isolation_passed=True,code_sha256=p.code_hashes())
    if which=='tests':evidence['s3_leakage_passed']=False
    for name,value in [('metrics_validation.json',metrics),('bootstrap_validation.json',boot),
                       ('calibration_status.json',audit),('p3b_parity.json',{'passed':True}),
                       ('evidence.json',evidence)]:p.write_json(tmp_path/name,value)
    det=dict(passed=which!='determinism',run2_hashes={'evidence.json':p.split.sha(tmp_path/'evidence.json')})
    p.write_json(tmp_path/'det.json',det)
    result=t.gate(tmp_path,tmp_path/'det.json',tmp_path/'evidence.json')
    assert result['passed']==(which is None)
