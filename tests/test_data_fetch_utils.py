import pytest

from data_fetch_utils import DataFetchError, raise_if_too_many_failed


def test_no_failures_does_not_raise():
    raise_if_too_many_failed("StockTwits", [], universe_size=24)


def test_failures_below_threshold_does_not_raise():
    # 11/24 = 45.8% < 50% threshold
    failed = [f"T{i}" for i in range(11)]
    raise_if_too_many_failed("StockTwits", failed, universe_size=24)


def test_failures_above_threshold_raises():
    # 13/24 = 54.2% > 50% threshold
    failed = [f"T{i}" for i in range(13)]
    with pytest.raises(DataFetchError) as exc_info:
        raise_if_too_many_failed("StockTwits", failed, universe_size=24)

    message = str(exc_info.value)
    assert "StockTwits" in message
    assert "13/24" in message
    assert "54%" in message


def test_exactly_at_threshold_does_not_raise():
    # Guard uses strict ">", so exactly 50% should not raise.
    failed = [f"T{i}" for i in range(12)]
    raise_if_too_many_failed("StockTwits", failed, universe_size=24)


def test_empty_universe_does_not_raise():
    raise_if_too_many_failed("StockTwits", [], universe_size=0)


def test_all_failed_raises():
    failed = [f"T{i}" for i in range(24)]
    with pytest.raises(DataFetchError):
        raise_if_too_many_failed("StockTwits", failed, universe_size=24)


def test_custom_max_ratio_is_respected():
    # 3/24 = 12.5%, above a strict 10% ratio
    failed = [f"T{i}" for i in range(3)]
    with pytest.raises(DataFetchError):
        raise_if_too_many_failed("StockTwits", failed, universe_size=24, max_ratio=0.10)
