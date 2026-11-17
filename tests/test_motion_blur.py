import pytest

from postfx.motion_blur import (
    velocity,
    tile_max,
    reconstruct,
    shutter,
    clear_history
)


def test_velocity():
    assert velocity((0.0, 0.0), (10.0, 0.0), 0.1) == (100.0, 0.0)

def test_velocity_dt0():
    assert velocity((0.0, 0.0), (10.0, 0.0), 0.0) == (0.0, 0.0)

def test_tile_max_first():
    assert tile_max([(3.0, 0.0), (0.0, 1.0), (0.0, 0.0)], 2)[0] == (3.0, 0.0)

def test_tile_max_empty():
    assert tile_max([], 2) == []

def test_tile_max_count():
    assert len(tile_max([(1.0, 0.0), (2.0, 0.0), (0.0, 1.0), (0.0, 2.0)], 2)) == 4

def test_shutter_60():
    assert shutter(0.5, 60) == pytest.approx(1.0 / 120.0)

def test_shutter_30():
    assert shutter(0.5, 30) == pytest.approx(1.0 / 60.0)

def test_shutter_clamp():
    assert shutter(1.0, 60) == 0.25

def test_reconstruct_same():
    assert reconstruct((1.0, 0.0, 0.0), (0.0, 0.0), 1.0, 1.0) == (1.0, 0.0, 0.0)

def test_reconstruct_diff():
    assert reconstruct((1.0, 0.0, 0.0), (0.0, 0.0), 1.0, 2.0) == (1.0, 0.0, 0.0)

def test_reconstruct_zero_velocity():
    assert reconstruct((1.0, 0.0, 0.0), (0.0, 0.0), 0.0, 0.0) == (1.0, 0.0, 0.0)

def test_clear_cut():
    assert clear_history(True) == []

def test_clear_keep():
    assert clear_history(False) == [(1.0, 2.0)]

def test_shutter_negative():
    assert shutter(-1.0, 60) == 0.0

def test_history_len():
    assert len(clear_history(False)) == 1
