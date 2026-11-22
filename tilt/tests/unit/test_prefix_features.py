"""S3.5 items 1--10, heads, pooled baselines and diagnostic boundaries."""
import hashlib
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tilt.features import prefix_features as p
from tilt.labels import tilt_rules as rules
from tilt.labels import dev_split as split


def fixture(n=15, plies=40):
    games, moves = [], []
    for i in range(n):
        gid = f'fixture-game-{i:03}'
        games.append(dict(cohort='old', player_id='fixture-player', player='synthetic', game_id=gid,
            raw_game_id=gid, color='white', session_id='session', start_ms=i * 100000,
            end_ms=i * 100000 + 60000, end_upper_ms=i * 100000 + 60001,
            rating=1800-i*3, opponent_rating=1800, result_score=[0., .5, 1., 0.][i % 4],
            speed='blitz', status='resign', plies=plies, initial_seconds=180., increment_seconds=2.,
            assignment='development', part='train', rematch_streak_before=0., losing_streak_before=0.,
            rest_gap_seconds=40. if i else np.nan, recent_form=.5 if i else np.nan))
        for ply in range(1, plies + 1):
            moves.append(dict(player='synthetic' if ply % 2 else 'opponent', game_id=gid,
                color='white' if ply % 2 else 'black', ply=ply, cpl=float((ply*7+i*3) % 120),
                judgement=['inaccuracy', 'mistake', 'blunder', None][ply % 4],
                think_seconds=float(1+((ply+i) % 5)), risk=bool(ply % 3), attack=bool(ply % 4),
                defensive=bool(ply % 5), style_switch=bool(ply % 2), sacrifice_heuristic=bool(ply % 7 == 0),
                eval_after_cp=float(ply * 4), eval_after_mate=np.nan, clock_seconds=float(180-ply),
                material_after=float(ply % 3), legal_moves=25., phase='opening' if ply <= 20 else 'middlegame'))
    return pd.DataFrame(games), pd.DataFrame(moves)


def target(games, i=12):
    return games.iloc[[i]]


def snapshot(games, moves, i=12):
    return p.build_player(games, moves, target(games, i))


def assert_bytes(a, b):
    for x, y in zip(a, b):
        pd.testing.assert_frame_equal(x, y, check_exact=True)
        assert x.to_json(double_precision=15) == y.to_json(double_precision=15)


def test_registry_allowlist_both_candidates_both_heads():
    g, m = fixture()
    pre, p20 = snapshot(g, m)
    combined = pre.merge(p20, on=p.IDS+['part'], validate='one_to_one')
    reg = p.registry()
    assert not reg.column.duplicated().any()
    assert set(reg.columns) == {'column','block','family','source_fields','minimum_data','missing_value_rule'}
    forbidden = {'result_score','status','plies','length_bucket','baseline_kind','end_ms','n_fired','n_missing','label'}
    assert not set(reg.column) & forbidden
    assert not any(c.startswith('lf_input__') for c in reg.column)
    assert all(s.startswith(('header.', 'available_', 'stored_prior_', 'prior_game.', 'prefix_1_20.')) for s in reg.source_fields)
    for head in ('pre','p20'):
        for candidate in ('M-v3','P3-B@20'):
            matrix = p.model_matrix(pre if head == 'pre' else combined, head, candidate)
            assert set(matrix) <= set(reg.loc[reg.block.isin(['pre'] if head=='pre' else ['pre','p20']), 'column'])
            assert not set(matrix) & forbidden
            bad = combined.assign(lf_input__secret=1)
            with pytest.raises(ValueError):
                p.model_matrix(bad, head, candidate)
    with pytest.raises(ValueError):
        p.model_matrix(combined, 'p20', 'P3-B/v3')


def test_future_perturbations_result_status_length_end_other_players():
    g, m = fixture()
    expected = snapshot(g, m)
    current = g.iloc[12].game_id
    changed = m.copy()
    mask = changed.game_id.eq(current) & changed.ply.gt(20)
    for c in ('cpl','think_seconds','eval_after_cp','clock_seconds','risk','attack','sacrifice_heuristic'):
        changed.loc[mask,c] = 999 if changed[c].dtype != bool else False
    gg = g.copy()
    gg.loc[12,['result_score','status','plies','end_ms','end_upper_ms']] = [1.,'mate',999,1e12,1e12]
    gg = gg.iloc[:13].copy()
    changed = changed[changed.game_id.isin(gg.game_id)].copy()
    other = g.copy()
    other.player_id = 'another-player'
    other.rating = 9999
    assert_bytes(expected, snapshot(pd.concat([gg,other],ignore_index=True), changed))


def test_truncation_equivalence_and_pre_game_independence():
    g, m = fixture()
    expected = snapshot(g, m)
    current = g.iloc[12]
    kept = g.end_upper_ms.lt(current.start_ms) | g.game_id.eq(current.game_id)
    mm = m[m.game_id.isin(g.loc[kept,'game_id']) & (~m.game_id.eq(current.game_id) | m.ply.le(20))]
    assert_bytes(expected, snapshot(g[kept],mm))
    gg, terminals = p.aggregate_player(g,m)
    prior = rules.label_train(gg,gg.assign(split='train'),terminals)
    lookup={(x['game_id'],x['color']):x for x in prior.to_dict('records')}
    original=p.pre_features(gg.iloc[12].to_dict(),gg,lookup)
    no_current=m[~m.game_id.eq(current.game_id)]
    altered,_=p.aggregate_player(g,no_current)
    actual=p.pre_features(altered.iloc[12].to_dict(),altered,lookup)
    pd.testing.assert_series_equal(pd.Series(original),pd.Series(actual),check_exact=True)


def test_baselines_pooled_independent_of_current_plies():
    g,m=fixture(n=30)
    pre,_=snapshot(g,m,25)
    g.loc[25,'plies']=200
    other,_=snapshot(g,m,25)
    pd.testing.assert_frame_equal(pre,other,check_exact=True)
    assert pre.baseline_games.iloc[0]==25
    assert pre.baseline_risk_rate_games.iloc[0]==25


def test_prefix_support_short_rows_and_point_of_view():
    g,m=fixture()
    g.loc[12,'plies']=19
    m=m[~(m.game_id.eq(g.iloc[12].game_id)&m.ply.gt(19))]
    pre,p20=snapshot(g,m)
    assert len(pre)==1 and p20.empty
    g,m=fixture()
    row=p.prefix_stats(g.iloc[12].to_dict(),m)
    assert row['win_percent']==p.win_percent(-80.,None)
    assert row['material_balance']==-2.
    with pytest.raises(ValueError,match='exactly'):
        p.prefix_stats(g.iloc[12].to_dict(),m[~(m.game_id.eq(g.iloc[12].game_id)&m.ply.eq(20))])


@pytest.mark.parametrize('assignment', ['A_prime','B_prime','drop_shared_development','history_only'])
def test_holdout_and_dropped_targets_refused(assignment):
    g,m=fixture()
    g.loc[12,'assignment']=assignment
    with pytest.raises(ValueError,match='forbidden'):
        snapshot(g,m)


def test_split_drop_refused():
    g,m=fixture()
    g.loc[12,'part']='drop_shared_split'
    with pytest.raises(ValueError):snapshot(g,m)


def test_deterministic_output_table_hashes(tmp_path):
    g,m=fixture()
    pre,p20=snapshot(g,m)
    labels=p.build_player(g,m,target(g),'labels')
    for name,frame in [('pre',pre),('p20',p20),('labels',labels)]:
        a,b=tmp_path/(name+'1.parquet'),tmp_path/(name+'2.parquet')
        p.write_tables(iter([frame]),[a]);p.write_tables(iter([frame.copy()]),[b])
        assert split.sha(a)==split.sha(b)


def test_label_adapter_exact_frozen_s1_rules():
    g,m=fixture()
    gg,t=p.aggregate_player(g,m)
    expected=rules.label_train(gg,target(g).assign(split='train'),t).drop(columns='split')
    actual=p.build_player(g,m,target(g),'labels')
    pd.testing.assert_frame_equal(expected,actual[expected.columns],check_exact=True)
    assert rules.DESIGN.hash=='6393da7f066e1a8c3892fd894e381cb70ceb1f24d00366e97ef5ef40794fb0fb'


@pytest.mark.parametrize('true_overlap',[False,True])
def test_uncertain_or_overlapping_prior_absent_from_every_direct_pre_input(true_overlap):
    g,m=fixture()
    g.loc[11,'end_upper_ms']=g.iloc[12].start_ms+5000
    g.loc[11,'end_ms']=g.iloc[12].start_ms+1000 if true_overlap else np.nan
    expected=snapshot(g,m)[0]
    gg=g.copy();mm=m.copy()
    gg.loc[11,'result_score']=1.
    gg.loc[11,'end_ms']=g.iloc[12].start_ms+2000
    mask=mm.game_id.eq(g.iloc[11].game_id)
    mm.loc[mask,'cpl']=500
    mm.loc[mask,'attack']=False
    actual=snapshot(gg,mm)[0]
    pd.testing.assert_frame_equal(expected,actual,check_exact=True)
    assert p.r_pre(expected.iloc[0])==p.r_pre(actual.iloc[0])
    assert expected.ctx_games_before.iloc[0]==11


def test_probe_train_only_stop_and_null_boundaries(monkeypatch):
    # <3 players avoids fitting; single-column probe remains train-only.
    pre=pd.DataFrame([dict(cohort='old',player_id='a',game_id=str(i),color='white',part='train',rating=float(i)) for i in range(10)])
    val=pre.copy();val.game_id='v'+val.game_id;val.part='V_A';val.rating=-999
    lengths=pre[p.IDS].copy();lengths['plies']=[25]*5+[80]*5
    result=p.length_probe(pd.concat([pre,val]),pre.iloc[:0],lengths)
    row=next(x for x in result['single'] if x['column']=='rating' and x['threshold']==40)
    assert row['rows']==10 and row['auc']==1 and result['stop']


def test_registry_history_exclusions():
    reg=p.registry(p.HISTORY)
    assert not set(p.HISTORY)&set(reg.column)
    assert 'prev_label' in set(reg.column)


def real_config():
    value = os.environ.get('S3_REAL_CONFIG')
    if not value:
        pytest.skip('set S3_REAL_CONFIG to portable read-only input paths for real sample tests')
    return json.loads(Path(value).read_text())


@pytest.mark.parametrize('cohort', ['old', 'new'])
def test_real_development_future_truncation_pre_independence_and_s1_regression(cohort):
    config = real_config()
    headers = split.load_headers(config['old_root'], config['new_root'], config['s2'])
    pool = headers[headers.assignment.eq('development')]
    players = pool[pool.cohort.eq(cohort)].sort_values('split_key').player_id.drop_duplicates()
    player = players.iloc[0]  # Also among the CLI's deterministic <=5 smoke players.
    g = headers[headers.player_id.eq(player) & headers.cohort.eq(cohort)].sort_values(['start_ms','game_id']).reset_index(drop=True)
    g['part'] = 'train'  # Only this explicit development target is built, no split is assigned here.
    # E3.6: no unavailable prior in ANY session on the real truncation sample.
    eligible = []
    for i,r in g.iterrows():
        earlier = g[g.start_ms.lt(r.start_ms)]
        if r.assignment == 'development' and r.plies >= 20 and len(earlier) >= 5 and not earlier.end_upper_ms.ge(r.start_ms).any():
            eligible.append(i)
    assert eligible
    i = eligible[min(5, len(eligible)-1)]
    root = config['old_root'] if cohort == 'old' else config['new_root']
    m = pd.read_parquet(Path(root)/'features/moves.parquet', columns=p.MOVE_COLS,
                        filters=[('game_id','in',g.raw_game_id.tolist())])
    expected = snapshot(g,m,i)
    current = g.iloc[i]
    gg = g[g.start_ms.le(current.start_ms)].copy()
    gg.loc[gg.game_id.eq(current.game_id),['result_score','status','plies','end_ms','end_upper_ms']] = [1.,'mate',999,1e15,1e15]
    mm = m[m.game_id.isin(gg.raw_game_id)].copy()
    mask = mm.game_id.eq(current.raw_game_id) & mm.ply.gt(20)
    mm.loc[mask,'cpl'] = 9999.
    mm.loc[mask,'think_seconds'] = 9999.
    mm.loc[mask,'eval_after_cp'] = 9999.
    mm.loc[mask,'clock_seconds'] = 9999.
    for c in ('attack','risk','defensive','style_switch','sacrifice_heuristic'):
        mm.loc[mask,c] = False if pd.api.types.is_bool_dtype(mm[c]) else 0.
    assert_bytes(expected,snapshot(gg,mm,i))
    kept = g.end_upper_ms.lt(current.start_ms) | g.game_id.eq(current.game_id)
    truncated = m[m.game_id.isin(g.loc[kept,'raw_game_id']) & (~m.game_id.eq(current.raw_game_id)|m.ply.le(20))]
    assert_bytes(expected,snapshot(g[kept],truncated,i))
    agg,t = p.aggregate_player(g,m)
    needed = agg[agg.end_upper_ms.lt(current.start_ms) & agg.session_id.eq(current.session_id)]
    labs = p.frozen_labels(agg,needed,t) if len(needed) else pd.DataFrame()
    lookup = {(x['game_id'],x['color']):x for x in labs.to_dict('records')}
    without,_ = p.aggregate_player(g,m[~m.game_id.eq(current.raw_game_id)])
    pd.testing.assert_series_equal(pd.Series(p.pre_features(agg.iloc[i].to_dict(),agg,lookup)),
                                   pd.Series(p.pre_features(without.iloc[i].to_dict(),without,lookup)),check_exact=True)
    regression_counts = {}
    if cohort == 'old':
        for name in ('by_player','by_time'):
            source = pd.read_parquet(Path(config['s1'])/f'labels_{name}_train.parquet',
                columns=['game_id','color','player_id','label'],filters=[('player_id','==',player)])
            if source.empty:
                continue
            wanted = agg.merge(source[['game_id','color']],on=['game_id','color'],validate='one_to_one')
            actual = p.frozen_labels(agg,wanted,t)
            joined = source.merge(actual[['game_id','color','label']],on=['game_id','color'],suffixes=('_s1','_s3'),validate='one_to_one')
            assert len(joined)==len(source)
            assert joined.label_s1.eq(joined.label_s3).all()
            regression_counts[name]=len(joined)
    out = Path(config['audit_out'])
    out.mkdir(parents=True,exist_ok=True)
    (out/f'real_tests_{cohort}.json').write_text(json.dumps(dict(passed=True,players=1,targets=1,
        regression_counts=regression_counts,code_hash=p.code_hash_text()),indent=2)+'\n')


def test_parallel_player_streaming_has_identical_table_hashes(tmp_path):
    from concurrent.futures import ProcessPoolExecutor
    import multiprocessing
    g,m=fixture()
    (tmp_path/'features').mkdir()
    m.to_parquet(tmp_path/'features/moves.parquet',index=False)
    tasks=[(tmp_path,g,target(g),'features',(),tmp_path)]*2
    one=[tmp_path/'one_pre.parquet',tmp_path/'one_p20.parquet']
    two=[tmp_path/'two_pre.parquet',tmp_path/'two_p20.parquet']
    p.write_tables(map(p.worker,tasks),one)
    with ProcessPoolExecutor(max_workers=2,mp_context=multiprocessing.get_context('spawn')) as executor:
        p.write_tables(executor.map(p.worker,tasks),two)
    assert [split.sha(x) for x in one]==[split.sha(x) for x in two]


def test_prefix_reference_includes_other_speeds_and_excludes_unavailable():
    g,m=fixture()
    g.loc[:11,'speed']='rapid'
    g.loc[11,'end_upper_ms']=g.iloc[12].start_ms
    pre,p20=snapshot(g,m)
    assert pre.baseline_games.iloc[0]==0
    assert p20.p20_z_cpl_mean_w300.notna().all()


def test_current_end_cannot_activate_current_whole_game_as_own_baseline():
    g,m=fixture()
    expected=snapshot(g,m)
    g.loc[12,['end_ms','end_upper_ms']]=0
    assert_bytes(expected,snapshot(g,m))


def test_holdout_moves_not_read_by_worker(tmp_path, monkeypatch):
    g,m=fixture()
    g.loc[13:,'assignment']='B_prime'
    seen=[]
    def read(path,columns,filters,use_threads):
        ids=filters[0][2]
        seen.extend(ids)
        return m[m.game_id.isin(ids)][columns]
    monkeypatch.setattr(pd,'read_parquet',read)
    p.worker((tmp_path,g,target(g),'features',(),tmp_path))
    assert not set(g.loc[g.assignment.eq('B_prime'),'raw_game_id']) & set(seen)


def test_describe_ignores_validation_statistics():
    g,m=fixture()
    pre,p20=snapshot(g,m)
    labels=p.build_player(g,m,target(g),'labels')
    extra=labels.copy();extra.game_id='validation';extra.part='V_A';extra.label='TILT'
    result=p.describe(pre,p20,pd.concat([labels,extra],ignore_index=True))
    assert next(x['rows'] for x in result['labels'] if x.get('population')=='P-all' and x['cohort']=='all')==1
    assert all('passed' not in x for gs in result['gates_description'].values() for x in gs.values())


def gate_fixture(tmp_path,monkeypatch):
    from types import SimpleNamespace
    g,m=fixture(n=8)
    # The synthetic population has no defect; real builds retain the E4 count 34.
    monkeypatch.setattr(p, 'E4_EXPECTED', dict(train=0, V_A=0, V_B=0))
    (tmp_path/'features').mkdir()
    m.to_parquet(tmp_path/'features/moves.parquet', index=False)
    pd.DataFrame(columns=p.EXCLUSION_COLS).to_csv(tmp_path/'excluded_incomplete_moves.csv', index=False)
    g['physical_id']=g.game_id
    manifest=g[p.IDS+['physical_id','session_id','start_ms','part']]
    manifest.to_parquet(tmp_path/'dev_split_manifest.parquet',index=False)
    (tmp_path/'dev_split_manifest.sha256').write_text(split.sha(tmp_path/'dev_split_manifest.parquet')+'  dev_split_manifest.parquet\n')
    labels=p.build_player(g,m,g,'labels')
    pre,p20=p.build_player(g,m,g,'features')
    files=['labels_dev.parquet','features_pre.parquet','features_p20.parquet']
    for f,frame in zip(files,[labels,pre,p20]):frame.to_parquet(tmp_path/f,index=False)
    p.registry().to_csv(tmp_path/'feature_registry.csv',index=False)
    p.code_hash(tmp_path)
    for name,outputs in [('labels',files[:1]),('features',files[1:]+['excluded_incomplete_moves.csv'])]:
        (tmp_path/(name+'_build.json')).write_text(json.dumps(dict(smoke=False,excluded_history=[],code_hash=p.code_hash_text(),
            design_hash=rules.DESIGN.hash,split_sha=split.sha(tmp_path/'dev_split_manifest.parquet'),
            output_sha256={f:split.sha(tmp_path/f) for f in outputs})))
    for name in ['by_player','by_time']:
        labels.iloc[:1].to_parquet(tmp_path/f'labels_{name}_train.parquet',index=False)
    (tmp_path/'label_regression.json').write_text(json.dumps(dict(complete=True,design_hash=rules.DESIGN.hash,
        checks={n:dict(expected=1,checked=1,matches=1) for n in ['by_player','by_time']})))
    (tmp_path/'test_evidence.json').write_text(json.dumps(dict(passed=True,code_hash=p.code_hash_text())))
    for c in ['old','new']:
        (tmp_path/f'real_tests_{c}.json').write_text(json.dumps(dict(passed=True,code_hash=p.code_hash_text())))
    (tmp_path/'length_probe.json').write_text(json.dumps(dict(stop=False,single=[])))
    monkeypatch.setattr(p,'verify_sources',lambda args:None)
    args=SimpleNamespace(out=tmp_path,s3=tmp_path,s1=tmp_path,old_root=tmp_path,new_root=tmp_path,
        test_evidence=tmp_path/'test_evidence.json',decisions=None)
    return args,g


@pytest.mark.parametrize('failure',[None,'tests','regression','probe','pre','provenance','registry','real_sample','exclusion_hash'])
def test_gate_fail_closed_for_each_required_check(tmp_path,monkeypatch,failure):
    args,g=gate_fixture(tmp_path,monkeypatch)
    if failure=='tests':args.test_evidence=None
    elif failure=='regression':(tmp_path/'label_regression.json').unlink()
    elif failure=='probe':
        (tmp_path/'length_probe.json').write_text(json.dumps(dict(stop=True,single=[dict(block='pre',column='rating',threshold=40,stop=True)])))
    elif failure=='pre':
        pre=pd.read_parquet(tmp_path/'features_pre.parquet');pre.iloc[1:].to_parquet(tmp_path/'features_pre.parquet',index=False)
    elif failure=='provenance':
        path=tmp_path/'features_build.json';record=json.loads(path.read_text());record['smoke']=True;path.write_text(json.dumps(record))
    elif failure=='registry':
        reg=p.registry();reg.loc[0,'source_fields']='forbidden';reg.to_csv(tmp_path/'feature_registry.csv',index=False)
    elif failure=='real_sample':(tmp_path/'real_tests_new.json').unlink()
    elif failure=='exclusion_hash':
        path=tmp_path/'features_build.json';record=json.loads(path.read_text())
        record['output_sha256'].pop('excluded_incomplete_moves.csv');path.write_text(json.dumps(record))
    result=p.gate(args,g)
    assert result['passed']==(failure is None)
    assert (tmp_path/'s3_gate.json').exists()


def test_gate_requires_exact_written_probe_decision(tmp_path,monkeypatch):
    args,g=gate_fixture(tmp_path,monkeypatch)
    (tmp_path/'length_probe.json').write_text(json.dumps(dict(stop=True,single=[dict(block='pre',column='rating',threshold=40,stop=True)])))
    args.decisions=tmp_path/'decisions.json'
    args.decisions.write_text(json.dumps(dict(probe_sha=split.sha(tmp_path/'length_probe.json'),accepted_stops=[['pre','rating',40]])))
    assert p.gate(args,g)['passed']
    args.decisions.write_text(json.dumps(dict(probe_sha='wrong',accepted_stops=[['pre','rating',40]])))
    assert not p.gate(args,g)['passed']


def one_colour(moves, game_id, colour='white'):
    return moves[~moves.game_id.eq(game_id) | moves.color.eq(colour)].copy()


@pytest.mark.parametrize('colour', ['white', 'black'])
def test_e4_one_colour_target_excluded_both_heads_and_labels_retained(tmp_path, colour):
    g,m=fixture()
    m=one_colour(m,g.iloc[12].raw_game_id,colour)
    audit={}
    pre,p20=p.build_player(g,m,target(g),audit=audit)
    assert pre.empty and p20.empty
    found=pd.DataFrame(audit['exclusions'],columns=p.EXCLUSION_COLS)
    found.to_csv(tmp_path/'excluded_incomplete_moves.csv',index=False)
    saved=pd.read_csv(tmp_path/'excluded_incomplete_moves.csv')
    assert len(saved)==1 and saved.status.iloc[0]==p.DROP_INCOMPLETE
    assert saved.color_present.iloc[0]==colour
    assert saved.game_id.iloc[0]==g.iloc[12].game_id
    labels=p.build_player(g,m,target(g),'labels')
    assert len(labels)==1
    assert p.prefix_stats(g.iloc[12].to_dict(),m) is None


def test_e4_reference_skips_incomplete_but_keeps_pre_history():
    g,m=fixture()
    m=one_colour(m,g.iloc[11].raw_game_id)
    audit={}
    pre,p20=p.build_player(g,m,target(g),audit=audit)
    assert pre.ctx_games_before.iloc[0]==12
    assert pre.prev_plies.iloc[0]==40
    assert pre.baseline_games.iloc[0]==12
    assert pd.notna(pre.prev_label.iloc[0])
    agg,_=p.aggregate_player(g,m)
    complete=[x for x in agg.to_dict('records') if x['start_ms'] < g.iloc[12].start_ms and x['game_id']!=g.iloc[11].game_id]
    stats=[p.prefix_stats(x,m)['cpl_mean_w300'] for x in complete]
    current=p.prefix_stats(g.iloc[12].to_dict(),m)['cpl_mean_w300']
    median=np.median(stats)
    expected=(current-median)/max(1.4826*np.median(np.abs(stats-median)),p.FLOORS['cpl_mean_w300'])
    assert p20.p20_z_cpl_mean_w300.iloc[0]==expected
    assert audit['affected_targets']==dict(train=1,V_A=0,V_B=0)
    # Four complete games plus one defective game do not meet the minimum five.
    m=one_colour(m,g.iloc[4].raw_game_id)
    _,short_reference=p.build_player(g,m,target(g,5))
    assert short_reference.p20_z_cpl_mean_w300.isna().all()


def test_e4_reference_window_fills_to_200_complete_prefixes():
    g,_=fixture(n=205)
    game=g.iloc[-1].to_dict()
    complete=set(map(tuple,g.iloc[:204][['game_id','color']].to_numpy()))-{(g.iloc[202].game_id,'white')}
    reference=p.prefix_reference(game,g,complete)
    assert len(reference)==200
    assert reference.iloc[0].game_id==g.iloc[3].game_id
    assert g.iloc[202].game_id not in set(reference.game_id)


@pytest.mark.parametrize('missing', [[20],[2,4],[1,4,8]])
@pytest.mark.parametrize('index', [11,12])
def test_e4_non_one_colour_gap_still_raises(missing,index):
    g,m=fixture()
    m=m[~(m.game_id.eq(g.iloc[index].game_id)&m.ply.isin(missing))]
    with pytest.raises(ValueError,match='unhandled incomplete'):
        snapshot(g,m)


@pytest.mark.parametrize('part', ['A_prime','B_prime'])
def test_e4_frozen_target_rule_also_applies_to_holdouts(part):
    g,m=fixture()
    t=target(g).copy();t['part']=part
    m=one_colour(m,t.raw_game_id.iloc[0])
    inventory=p.move_inventory(t,m)
    found=p.incomplete_targets(t,inventory)
    assert len(found)==1 and found.status.iloc[0]==p.DROP_INCOMPLETE
    t['assignment']=part
    with pytest.raises(ValueError):p.build_player(g,m,t)


def test_e4_expected_count_stop_and_exact_part_counts():
    rows=pd.DataFrame(dict(part=['train']*20+['V_A']*9+['V_B']*5))
    assert p.check_incomplete_count(rows)==dict(train=20,V_A=9,V_B=5)
    with pytest.raises(ValueError,match='count stop'):p.check_incomplete_count(rows.iloc[1:])
    rows.loc[0,'part']='V_A'
    with pytest.raises(ValueError,match='count stop'):p.check_incomplete_count(rows)


@pytest.mark.parametrize('label', ['TILT','NOT','ABSTAIN'])
def test_e4_own_colour_stop(label):
    g,m=fixture(n=1)
    m=one_colour(m,g.iloc[0].raw_game_id,'black')
    inv=p.move_inventory(g,m)
    labels=g[p.IDS].assign(label=label)
    if label=='ABSTAIN':p.check_own_colour(inv,labels)
    else:
        with pytest.raises(ValueError,match='own-colour stop'):p.check_own_colour(inv,labels)
    p.check_own_colour(inv.assign(color_present='white'),labels)


def test_e4_publication_stop_keeps_feature_tables_unpublished(tmp_path):
    g,m=fixture()
    frames=snapshot(g,m)
    paths=[tmp_path/'features_pre.parquet',tmp_path/'features_p20.parquet']
    with pytest.raises(ValueError,match='count stop'):
        p.write_tables([frames],paths,before_publish=lambda:p.check_incomplete_count(pd.DataFrame(columns=['part'])))
    assert not any(path.exists() for path in paths)


def test_e4_short_game_has_no_prefix_exclusion_but_own_colour_check_applies():
    g,m=fixture(n=1,plies=19)
    m=one_colour(m,g.iloc[0].raw_game_id)
    inv=p.move_inventory(g,m)
    assert len(inv)==1 and inv.status.iloc[0]=='short'
    assert p.incomplete_targets(g,inv).empty
    pre,p20=p.build_player(g,m,g)
    assert len(pre)==1 and p20.empty


@pytest.mark.parametrize('outcome', ['success','count_stop','own_stop'])
def test_e4_feature_build_exclusion_file_and_prepublication_stops(tmp_path,monkeypatch,outcome):
    from types import SimpleNamespace
    g,m=fixture(n=8)
    g['cohort']='new';g['split_key']='synthetic-key'
    m=one_colour(m,g.iloc[6].raw_game_id,'black' if outcome=='own_stop' else 'white')
    root=tmp_path/'root';out=tmp_path/'out'
    (root/'features').mkdir(parents=True);out.mkdir()
    m.to_parquet(root/'features/moves.parquet',index=False)
    g[p.IDS+['part']].to_parquet(out/'dev_split_manifest.parquet',index=False)
    labels=p.build_player(g,m,g,'labels')
    if outcome=='own_stop':labels.loc[labels.game_id.eq(g.iloc[6].game_id),'label']='NOT'
    labels.to_parquet(out/'labels_dev.parquet',index=False)
    original_label_sha=split.sha(out/'labels_dev.parquet')
    monkeypatch.setattr(split,'load_headers',lambda *args:g)
    monkeypatch.setattr(p,'load_manifest',lambda args,headers:headers)
    monkeypatch.setattr(p,'verify_sources',lambda args:None)
    if outcome!='count_stop':monkeypatch.setattr(p,'E4_EXPECTED',dict(train=1,V_A=0,V_B=0))
    args=SimpleNamespace(old_root=root,new_root=root,s1=tmp_path/'s1',s2=tmp_path/'s2',s3=out,
        out=out,max_players=None,processes=1,exclude_history=None)
    if outcome=='success':
        record=p.build(args,'features')
        found=pd.read_csv(out/'excluded_incomplete_moves.csv')
        assert len(found)==1 and found.game_id.iloc[0]==g.iloc[6].game_id
        assert found.status.iloc[0]==p.DROP_INCOMPLETE
        assert record['rows']==[7,7]
        assert record['output_sha256']['excluded_incomplete_moves.csv']==split.sha(out/'excluded_incomplete_moves.csv')
        assert record['erratum4']['affected_targets']['train']==1
    else:
        with pytest.raises(ValueError,match='count stop' if outcome=='count_stop' else 'own-colour stop'):
            p.build(args,'features')
        assert not (out/'features_pre.parquet').exists()
        assert not (out/'features_p20.parquet').exists()
    assert split.sha(out/'labels_dev.parquet')==original_label_sha
