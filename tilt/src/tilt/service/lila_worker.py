"""Answer the tilt_queue of a lila site (lila modules/tilt), the way Kaladin answers kaladin_queue.

lila inserts one document per finished game and player. This worker fetches the player's games
from the site's public export, runs Stockfish on new positions, rebuilds features in a separate
data root, scores the game and writes `response` back. Scores are behavioural proxies, not
measured emotions.

With `processed/models/deployed_v3.json` present (reports/label_v3_deployment.md), blitz games are
scored by M-v3 from a blitz-only data root, other speeds are skipped, and the previous P3-B path
runs as a hidden shadow until the pointer's `shadow_until` date. Without the pointer the worker
behaves exactly as before.
"""
import datetime
import json
import time
from pathlib import Path

import requests

from ..data import collect
from . import live_v3, score
from ..common.engine import analyze
from ..data.cohort_v3 import KEY as TRAINED_SETTINGS_KEY
from ..features.features import compute

# The export can lag behind lila's finish event; keep such requests queued for a while.
EXPORT_GRACE_SECONDS = 120
HISTORY_GAMES = 200
MISSING = ('No local feature rows', 'No matching local game')


def pending(coll, limit=50):
    return list(coll.find({'response': {'$exists': False}}).sort('queuedAt', 1).limit(limit))


def respond(coll, doc, pred=None, err=None, skip=None, shadow=None):
    # Omit empty fields: lila reads them as Option.
    response = {'at': datetime.datetime.now(datetime.UTC)}
    for name, value in (('pred', pred), ('err', err), ('skip', skip), ('shadow', shadow)):
        if value is not None:
            response[name] = value
    coll.update_one({'_id': doc['_id']}, {'$set': {'response': response}})


def age_seconds(doc):
    queued = doc['queuedAt']
    if queued.tzinfo is None:
        queued = queued.replace(tzinfo=datetime.UTC)
    return (datetime.datetime.now(datetime.UTC) - queued).total_seconds()


def prepare(roots, models, engine, nodes):
    """Analyze and rebuild features with the trained settings; settings key per root."""
    # Same feature settings as the trained model.
    config = json.loads((Path(models) / 'processed/features/manifest.json').read_text())
    budget = config['engine']['budget']
    keys = {}
    for root in roots:
        result = analyze(root, engine, nodes=budget.get('nodes', nodes), depth=budget.get('depth'), processes=1,
                         hash_mb=config['engine']['hash_mb'])
        keys[str(root)] = (result or {}).get('settings_key')
        compute(root, config['window_plies'], config['min_prior_games'], config['session_gap_minutes'],
                config['max_history_games'])
    return keys


def p3b(data, doc, models):
    """The previous scorer's answer: pred dict, or raises like score.run."""
    result = score.run(data, doc['userId'], doc['gameId'], models=models)
    game = result['games'][0]
    return dict(score=int(round(game['weak_model_tilt_score'])), flag=bool(game['weak_model_tilt_flag']),
                factors=[factor['feature'] for factor in game['top_factors']])


def answer(coll, docs, data, models, lila_url, engine, nodes=5000, data_v3=None):
    """Score queued docs. Returns the number of answered docs."""
    v3 = live_v3.load(models)
    if v3 is not None:
        return answer_v3(coll, docs, data, models, lila_url, engine, v3,
                         Path(data_v3) if data_v3 else Path(data).with_name(Path(data).name + '-v3'), nodes)
    users = sorted({doc['userId'] for doc in docs})
    failed, unreachable = {}, set()
    for user in users:
        try:
            collect.collect_api(data, {user}, max_games=HISTORY_GAMES, base_url=lila_url)
        except (requests.ConnectionError, requests.Timeout):
            unreachable.add(user)  # site not up yet: keep the docs queued
        except Exception as exc:  # e.g. closed account: answer that user's docs
            failed[user] = f'export failed: {type(exc).__name__}'
    docs = [doc for doc in docs if doc['userId'] not in unreachable]
    if len(failed) + len(unreachable) < len(users):
        prepare([data], models, engine, nodes)
    answered = 0
    for doc in docs:
        if doc['userId'] in failed:
            respond(coll, doc, err=failed[doc['userId']])
            answered += 1
            continue
        try:
            pred = p3b(data, doc, models)
        except ValueError as exc:
            missing = str(exc).startswith(MISSING)
            if missing and age_seconds(doc) < EXPORT_GRACE_SECONDS:
                continue
            respond(coll, doc, err='game not available' if missing else str(exc))
            answered += 1
            continue
        except Exception as exc:
            respond(coll, doc, err=f'scoring failed: {type(exc).__name__}')
            answered += 1
            continue
        respond(coll, doc, pred=pred)
        answered += 1
    return answered


def stored_speed(data, game_id):
    """Speed of a game in the all-speed (P3-B) root, if it was exported there."""
    import pandas as pd
    path = Path(data) / 'processed/features/games.parquet'
    if not path.exists():
        return None
    rows = pd.read_parquet(path, columns=['game_id', 'speed'], filters=[('game_id', '==', game_id)])
    return str(rows.speed.iloc[0]) if len(rows) else None


def answer_v3(coll, docs, data, models, lila_url, engine, v3, data_v3, nodes=5000):
    shadow = v3.shadow_on()
    failed, unreachable = {}, set()
    # lila sends the speed; non-blitz docs need no export or engine work.
    skipped = [doc for doc in docs if doc.get('speed') not in (None, live_v3.SPEED)]
    for doc in skipped:
        respond(coll, doc, skip='speed')
    docs = [doc for doc in docs if doc.get('speed') in (None, live_v3.SPEED)]
    users = sorted({doc['userId'] for doc in docs})
    for user in users:
        try:
            if shadow:
                collect.collect_api(data, {user}, max_games=HISTORY_GAMES, base_url=lila_url)
            # Filter blitz here: a local lila answers perfType exports from lila-search, which it may lack.
            collect.collect_api(data_v3, {user}, max_games=HISTORY_GAMES, base_url=lila_url,
                                keep_perf=live_v3.SPEED)
        except (requests.ConnectionError, requests.Timeout):
            unreachable.add(user)
        except requests.HTTPError as exc:
            status = getattr(exc.response, 'status_code', None)
            if status is not None and status >= 500:
                # lila answers exports with 503 for 20 s after boot (web HttpFilter.WarmupFilter): retry next pass.
                unreachable.add(user)
            else:
                failed[user] = f'export failed: HTTP {status}'
        except Exception as exc:
            failed[user] = f'export failed: {type(exc).__name__}'
    docs = [doc for doc in docs if doc['userId'] not in unreachable]
    keys = {}
    if len(failed) + len(unreachable) < len(users):
        keys = prepare(([data] if shadow else []) + [data_v3], models, engine, nodes)
    settings_ok = keys.get(str(data_v3)) == TRAINED_SETTINGS_KEY
    root = data_v3 / 'processed'
    answered = len(skipped)
    touched = {}
    for doc in docs:
        user = doc['userId']
        if user in failed:
            respond(coll, doc, err=failed[user])
            answered += 1
            continue
        if not settings_ok:
            respond(coll, doc, err='engine settings differ from training')
            answered += 1
            continue
        try:
            result = live_v3.assess(v3, root, user, doc['gameId'])
        except ValueError as exc:
            missing = str(exc).startswith(MISSING)
            if missing and doc.get('speed') is None:
                speed = stored_speed(data, doc['gameId']) if shadow else None
                if speed is not None and speed != live_v3.SPEED:
                    respond(coll, doc, skip='speed')
                    answered += 1
                    continue
            if missing and age_seconds(doc) < EXPORT_GRACE_SECONDS:
                continue
            respond(coll, doc, err='game not available' if missing else str(exc))
            answered += 1
            continue
        except Exception as exc:
            respond(coll, doc, err=f'scoring failed: {type(exc).__name__}')
            answered += 1
            continue
        hidden = None
        if shadow and 'pred' in result:
            try:
                hidden = dict(model='P3-B', **p3b(data, doc, models))
            except Exception as exc:  # the shadow never blocks or changes the shown answer
                hidden = dict(model='P3-B', err=type(exc).__name__)
        respond(coll, doc, pred=result.get('pred'), skip=result.get('skip'), shadow=hidden)
        touched.setdefault(user, set()).add(doc['_id'])
        answered += 1
    for user in sorted(touched):
        refresh(coll, root, user, skip=touched[user])
    return answered


def refresh(coll, root, user, limit=5, skip=()):
    """E7 needs the next game: recompute pending rule checks of this player's earlier games."""
    query = {'userId': user, 'response.pred.v': 3, 'response.pred.rules.pending': 'E7'}
    updated = 0
    for doc in coll.find(query).sort('queuedAt', -1).limit(limit + len(skip)):
        if doc['_id'] in skip:
            continue  # just answered from the same export
        try:
            rules = live_v3.refresh_rules(root, user, doc['gameId'])
        except Exception:
            continue
        if rules != doc['response']['pred']['rules']:
            coll.update_one({'_id': doc['_id']}, {'$set': {'response.pred.rules': rules}})
            updated += 1
    return updated


def serve(mongo_uri, db_name, data, models, lila_url, engine, interval=10, once=False, data_v3=None):
    from pymongo import MongoClient
    coll = MongoClient(mongo_uri)[db_name]['tilt_queue']
    Path(data).mkdir(parents=True, exist_ok=True)
    if data_v3:
        Path(data_v3).mkdir(parents=True, exist_ok=True)
    total = 0
    while True:
        docs = pending(coll)
        if docs:
            answered = answer(coll, docs, data, models, lila_url, engine, data_v3=data_v3)
            total += answered
            print(f'{time.strftime("%H:%M:%S")} answered {answered}/{len(docs)}', flush=True)
        if once:
            return {'answered': total}
        if not docs or answered < len(docs):
            time.sleep(interval)
