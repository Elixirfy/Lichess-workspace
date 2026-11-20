"""Human labels only. Never import or derive a label from a behavioural feature."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import time

# Earlier v1 consent could be entered for arbitrary usernames. Require a new
# owner-authenticated consent instead of silently treating those as verified.
CONSENT_VERSION = 'draft-research-v2-oauth'
# Draft questionnaire; English comments describe intended constructs, not validated scales.
QUESTIONNAIRE = {
    'frustration': 'Tôi cảm thấy bực bội trong ván này.',  # frustration
    'anger': 'Tôi cảm thấy tức giận trong ván này.',  # anger
    'win_back': 'Tôi muốn thắng lại ngay để gỡ ván thua.',  # urge to win back
    'impulsiveness': 'Tôi đi nước bốc đồng, thiếu cân nhắc.',  # impulsiveness
    'focus': 'Tôi giữ được sự tập trung trong ván này.',  # focus (not reverse-scored here)
}
TILT_ITEM = 'Bạn cảm thấy “tilt” (bực bội, mất bình tĩnh hoặc chơi bốc đồng) ở mức nào?'


def salt():
    value = os.environ.get('TILT_SALT', '')
    if len(value) < 16:
        raise ValueError('Set TILT_SALT to a private stable salt of at least 16 characters')
    return value


def private_id(value):
    return hmac.new(salt().encode(), value.encode(), hashlib.sha256).hexdigest()


def pseudonym(username):
    return private_id(username.strip().lower())


def database(data):
    folder = Path(data) / 'raw' / 'labels'
    folder.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(folder / 'labels.sqlite')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS consents (
      player_id TEXT NOT NULL, consent_version TEXT NOT NULL, accepted_ms INTEGER NOT NULL,
      PRIMARY KEY(player_id,consent_version));
    CREATE TABLE IF NOT EXISTS labels (
      label_id INTEGER PRIMARY KEY,
      player_id TEXT NOT NULL,
      game_id TEXT,
      session_id TEXT,
      scope TEXT NOT NULL CHECK(scope IN ('game','moment','session')),
      ply_start INTEGER, ply_end INTEGER,
      tilt_score REAL NOT NULL CHECK(tilt_score >= 0 AND tilt_score <= 10),
      questionnaire_json TEXT,
      source TEXT NOT NULL CHECK(source IN ('self_report','expert','participant_verified')),
      annotator_id TEXT NOT NULL CHECK(length(annotator_id)>0),
      report_timestamp TEXT NOT NULL,
      report_ms INTEGER NOT NULL,
      delay_seconds REAL CHECK(delay_seconds IS NULL OR delay_seconds>=0),
      consent_version TEXT NOT NULL CHECK(length(consent_version)>0),
      CHECK((scope='game' AND game_id IS NOT NULL AND session_id IS NULL AND ply_start IS NULL AND ply_end IS NULL)
         OR (scope='moment' AND game_id IS NOT NULL AND session_id IS NULL AND ply_start IS NOT NULL AND ply_end IS NOT NULL AND ply_start>=1 AND ply_end>=ply_start)
         OR (scope='session' AND game_id IS NULL AND session_id IS NOT NULL AND ply_start IS NULL AND ply_end IS NULL))
    );
    CREATE INDEX IF NOT EXISTS labels_player_game ON labels(player_id,game_id);
    ''')
    fingerprint = hmac.new(salt().encode(), b'tilt-salt-fingerprint-v1', hashlib.sha256).hexdigest()
    legacy = hashlib.sha256(salt().encode()).hexdigest()
    row = conn.execute("SELECT value FROM metadata WHERE key='salt_fingerprint'").fetchone()
    if row and row[0] not in (fingerprint, legacy):
        conn.close()
        raise ValueError('TILT_SALT differs from the salt used for this label store')
    conn.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', ('salt_fingerprint', fingerprint))
    conn.commit()
    return conn


def validate_label(label):
    score = float(label['tilt_score'])
    if not 0 <= score <= 10:
        raise ValueError('Human tilt rating must be between 0 and 10')
    if label['source'] not in ('self_report', 'expert', 'participant_verified'):
        raise ValueError('Unknown human label source')
    if label['scope'] not in ('game', 'moment', 'session'):
        raise ValueError('Unknown label scope')
    if not label.get('annotator_id', '').strip() or not label.get('consent_version', '').strip():
        raise ValueError('Annotator id and consent version are required')
    for key, answer in (label.get('questionnaire') or {}).items():
        if key not in QUESTIONNAIRE or isinstance(answer, bool) or int(answer) != answer or not 1 <= answer <= 5:
            raise ValueError('Questionnaire answers must be known items with integer scores 1–5')
    return score


def insert_label(conn, label, game_end_ms=None, report_ms=None):
    score = validate_label(label)
    now = int(time.time() * 1000) if report_ms is None else int(report_ms)
    if game_end_ms is not None and now < game_end_ms:
        raise ValueError('Report cannot precede the end of its scope')
    if not conn.execute('SELECT 1 FROM consents WHERE player_id=? AND consent_version=?',
                        (label['player_id'], label['consent_version'])).fetchone():
        raise ValueError('Recorded participant consent is required')
    return conn.execute('''INSERT INTO labels
        (player_id,game_id,session_id,scope,ply_start,ply_end,tilt_score,questionnaire_json,source,
         annotator_id,report_timestamp,report_ms,delay_seconds,consent_version)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', (
        label['player_id'], label.get('game_id'), label.get('session_id'), label['scope'],
        label.get('ply_start'), label.get('ply_end'), score,
        json.dumps(label.get('questionnaire') or {}, ensure_ascii=False), label['source'],
        label['annotator_id'], datetime.fromtimestamp(now / 1000, timezone.utc).isoformat(), now,
        (now - game_end_ms) / 1000 if game_end_ms is not None else None, label['consent_version'])).lastrowid
