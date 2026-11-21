from copy import deepcopy
import json
from pathlib import Path

import pytest

from tilt.data.normalize import api_game
from tilt.data import storage

FIXTURES = Path(__file__).parent / 'fixtures'


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Tests must never access the network')
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)
    monkeypatch.setattr('requests.get', forbidden)
    monkeypatch.setattr('requests.post', forbidden)
    monkeypatch.setattr('requests.delete', forbidden)
    monkeypatch.setenv('TILT_SALT', 'offline-test-salt-never-for-real-data')


@pytest.fixture
def api_raw():
    return json.loads((FIXTURES / 'tiny.ndjson').read_text())


@pytest.fixture
def corpus(tmp_path, api_raw):
    def add(index, start=None, end=None, error=False, opponent='bob'):
        raw = deepcopy(api_raw)
        raw['id'] = f'game{index:04d}'
        raw['createdAt'] = start if start is not None else index * 100000
        raw['lastMoveAt'] = end if end is not None else raw['createdAt'] + 60000
        raw['players']['black']['user']['id'] = opponent
        if error:
            raw['analysis'][0]['eval'] = -900
        game, moves = api_game(raw, observed_ms=10000000)
        storage.append(tmp_path, [game], moves)
        return game
    return tmp_path, add
