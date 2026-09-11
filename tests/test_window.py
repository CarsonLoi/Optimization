"""
window_desirability() 是纯函数，不需要 ortools，独立测试。
"""

from shift_optimizer.config import SHIFT_CODES
from shift_optimizer.model import window_desirability


def _by_code(values: list[float]) -> dict[str, float]:
    return dict(zip(SHIFT_CODES, values))


def test_single_member_categories_are_always_zero():
    # A（24h）和 G（关闭）在各自类别里没有别的班次可比，恒为 0
    demand = [10] * 24
    d = _by_code(window_desirability(demand))
    assert d['A'] == 0.0
    assert d['G'] == 0.0


def test_all_zero_demand_gives_all_zero_desirability():
    d = window_desirability([0] * 24)
    assert d == [0.0] * len(SHIFT_CODES)


def test_prefers_the_16h_window_covering_more_demand():
    # 需求只落在 C 的窗口（05:00-21:00 对应下标 5..20），E 完全没覆盖到
    demand = [0] * 5 + [10] * 16 + [0] * 3
    d = _by_code(window_desirability(demand))
    assert d['C'] == 1.0
    assert d['E'] == 0.0


def test_prefers_the_8h_window_covering_more_demand():
    # 需求只落在下标 5..12（H 的窗口）。J 和 H 有部分重叠（8..12），也会分到一些；
    # L 和 N 跟这段完全不重叠，拿 0。H 覆盖最多，desirability 最高。
    demand = [0] * 5 + [10] * 8 + [0] * 11
    d = _by_code(window_desirability(demand))
    assert d['H'] == 1.0
    assert d['L'] == 0.0
    assert d['N'] == 0.0
    assert 0.0 < d['J'] < 1.0          # 与 H 重叠 5 小时(8..12)，但没 H 覆盖得全


def test_higher_total_demand_covered_wins():
    # C 覆盖下标 5..20（16 小时，每小时需求 1，总量 16）
    # E 覆盖下标 8..23，其中和 C 重叠的 8..20 需求也是 1，总量只有 13（< 16）
    # 16h 类别只有 C/E 两个成员，min-max 归一化后二选一必是 {0.0, 1.0}
    demand = [0] * 5 + [1] * 16 + [0] * 3
    d = _by_code(window_desirability(demand))
    assert d['C'] == 1.0
    assert d['E'] == 0.0


def test_equal_coverage_within_category_is_a_tie():
    # 精心构造 C 和 E 覆盖的需求总量相等 -> 组内归一化后都是 0（打平，谁都不占优）
    demand = [0] * 24
    demand[5:9] = [4, 4, 4, 4]      # 只有 C 覆盖 (下标5..8 在 C 的 5..20 内, 不在 E 的 8..23 -> 除了 8)
    demand[21:24] = [4, 4, 4]        # 只有 E 覆盖 (下标21..23 在 E 的 8..23 内, 不在 C 的 5..20 内)
    d = _by_code(window_desirability(demand))
    covered_c = sum(demand[5:21])
    covered_e = sum(demand[8:24])
    assert covered_c == covered_e            # 前置条件：构造的两组总量确实相等
    assert d['C'] == 0.0
    assert d['E'] == 0.0
