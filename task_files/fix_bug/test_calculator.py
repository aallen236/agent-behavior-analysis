from calculator import average, clamp


def test_average_basic():
    assert average([2, 4, 6]) == 4


def test_average_single_value():
    assert average([5]) == 5


def test_average_mixed():
    assert average([1, 2, 3, 4]) == 2.5


def test_clamp_inside():
    assert clamp(5, 0, 10) == 5


def test_clamp_low():
    assert clamp(-3, 0, 10) == 0


def test_clamp_high():
    assert clamp(42, 0, 10) == 10
