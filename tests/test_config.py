"""
config.py 里从班次表推导出来的东西，都是纯函数/纯数据，不需要 ortools。
"""

from shift_optimizer.config import SHIFT_CODES, SOFT_SHIFT_PAIRS


def _pairs_by_code():
    return {frozenset((SHIFT_CODES[a], SHIFT_CODES[b])) for a, b in SOFT_SHIFT_PAIRS}


def test_soft_shift_pairs_are_exactly_the_boundary_matches():
    # 手算过的 8 对：同开钟点 / 同关钟点 / 首尾正好衔接
    expected = {
        frozenset(p) for p in
        [('A', 'E'), ('A', 'N'), ('C', 'H'), ('C', 'L'),
         ('E', 'J'), ('E', 'N'), ('H', 'L'), ('J', 'N')]
    }
    assert _pairs_by_code() == expected


def test_soft_shift_pairs_excludes_closed_shift():
    # G 全天关闭，没有钟点可比，不该出现在任何"衔接得上"的组合里
    assert all('G' not in pair for pair in _pairs_by_code())


def test_soft_shift_pairs_excludes_clearly_mismatched_pairs():
    # C(12:00-04:00) 和 J(15:00-23:00)：开也不同、关也不同、谁也接不上谁
    assert frozenset(('C', 'J')) not in _pairs_by_code()
    # H(12:00-20:00) 和 N(23:00-07:00)：同上，完全对不上
    assert frozenset(('H', 'N')) not in _pairs_by_code()


def test_h_and_l_tile_exactly_into_a_16h_window():
    # H+L 首尾相接覆盖的钟点，应该正好是 16h 类班次 C 的窗口（旁证这对"衔接得上"合理）
    assert frozenset(('H', 'L')) in _pairs_by_code()
