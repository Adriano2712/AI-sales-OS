import pytest

from app.modules.jobs.handlers.discovery import split_target


@pytest.mark.parametrize(
    "total,n,expected",
    [
        (100, 3, [34, 33, 33]),
        (99, 3, [33, 33, 33]),
        (10, 1, [10]),
        (0, 3, [0, 0, 0]),
        (5, 0, []),
    ],
)
def test_split_target(total, n, expected):
    assert split_target(total, n) == expected


def test_split_target_sums_to_total():
    for total, n in [(100, 3), (7, 4), (1, 5), (250, 7)]:
        assert sum(split_target(total, n)) == total
