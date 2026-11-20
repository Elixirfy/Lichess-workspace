import io

import chess
import chess.pgn
import pytest

from tilt.core.formulas import (chances, win_percent, move_accuracy, game_accuracy, judgement, division, speed)


def test_known_winning_chances_and_clamping():
    assert chances(0) == 0
    assert chances(100) == pytest.approx(.1820517943832256)
    assert chances(1000) == chances(100000)
    assert chances(-100) == pytest.approx(-chances(100))
    assert chances(mate=1) > chances(1000)
    assert chances(mate=20) == chances(mate=10)
    assert chances(mate=0) < 0
    assert win_percent(mate=1) == win_percent(1000)
    assert win_percent(0) == 50


def test_accuracy_known_values():
    assert move_accuracy(50, 50) == 100
    assert move_accuracy(30, 60) == 100
    assert move_accuracy(60, 50) == pytest.approx(64.57982845372067)
    assert move_accuracy(100, 0) == 0
    assert move_accuracy(None, 50) is None


@pytest.mark.parametrize('cps,white,black', [([15, 15],100,100), ([-900,-900],10,100),
    ([15,900],100,10), ([-900,0],10,10), ([15]*20+[-900],50,100),
    ([-50,15]*50,76,76), ([-135,15]*50,54,54), ([-435,15]*50,20,20)])
def test_game_accuracy_port_from_lila_tests(cps, white, black):
    acc = game_accuracy([(15, None)] + [(cp, None) for cp in cps])
    assert acc['white'] == pytest.approx(white, abs=8)
    assert acc['black'] == pytest.approx(black, abs=8)


def test_judgements_mate_and_pov():
    assert judgement(0,None,-1000,None) == 'blunder'
    assert judgement(0,None,-150,None) == 'mistake'
    assert judgement(0,None,-60,None) == 'inaccuracy'
    assert judgement(0,None,1000,None, -1) == 'blunder'
    assert judgement(0,None,None,-1) == 'blunder'
    assert judgement(-1000,None,None,-1) == 'inaccuracy'
    assert judgement(None,2,1000,None) == 'inaccuracy'
    assert judgement(None,2,0,None) == 'blunder'
    assert judgement(None,None,0,None) is None


def test_divider_known_lila_game():
    pgn = chess.pgn.read_game(io.StringIO('''1. e4 e5 2. f4 d6 3. Nf3 exf4 4. Bc4 h6 5. O-O Bg4
    6. d4 Nc6 7. Bxf4 Nf6 8. Nc3 Be7 9. e5 dxe5 10. dxe5 Nh5 11. Be3 O-O
    12. h3 Bxf3 13. Qxf3 Nxe5 14. Bxf7+ Rxf7 15. Qxh5 Qf8 *'''))
    board, boards = pgn.board(), []
    for move in pgn.mainline_moves():
        boards.append(board.copy())
        board.push(move)
    middle, end = division(boards)
    assert 19 <= middle <= 25
    assert end is None
    assert division([chess.Board()]) == (None, None)
    assert division([chess.Board('8/8/8/8/8/4k3/8/4K3 w - - 0 1')]) == (None, 0)


def test_speed_boundaries():
    assert speed(60, 2) == 'bullet'
    assert speed(180, 0) == 'blitz'
    assert speed(480, 0) == 'rapid'
    assert speed(1500, 0) == 'classical'


def test_missing_eval_is_not_a_lost_or_created_mate():
    assert judgement(None,2,None,None) is None
    assert judgement(None,None,None,-2) is None
