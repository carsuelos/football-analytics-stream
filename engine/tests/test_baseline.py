import pytest

from engine.detectors import Ewma


def test_there_is_no_mean_before_the_first_sample() -> None:
    assert Ewma(600).mean is None


def test_the_first_sample_is_the_mean() -> None:
    b = Ewma(600)
    b.add(4.0, 30)
    assert (b.mean, b.variance) == (4.0, 0.0)


@pytest.mark.parametrize(
    ("gap_s", "mean", "std"),
    [
        (600, 5.0, 5.0),  # one half-life: halfway
        (1200, 7.5, 18.75**0.5),  # two: three-quarters of the way
        (0, 0.0, 0.0),  # no time has passed: no weight
    ],
)
def test_a_sample_weighs_more_the_longer_since_the_last(
    gap_s: float, mean: float, std: float
) -> None:
    b = Ewma(600)
    b.add(0.0, 100)
    b.add(10.0, 100 + gap_s)
    assert b.mean == pytest.approx(mean)
    assert b.std == pytest.approx(std)


def test_a_constant_series_has_no_spread() -> None:
    b = Ewma(600)
    for t in range(0, 900, 30):
        b.add(5.0, t)
    assert (b.mean, b.variance) == (5.0, 0.0)


def test_samples_must_come_in_time_order() -> None:
    b = Ewma(600)
    b.add(1.0, 60)
    with pytest.raises(ValueError, match="before the latest"):
        b.add(1.0, 59)


@pytest.mark.parametrize("half_life_s", [0, -1])
def test_the_half_life_must_be_positive(half_life_s: float) -> None:
    with pytest.raises(ValueError, match="positive"):
        Ewma(half_life_s)
