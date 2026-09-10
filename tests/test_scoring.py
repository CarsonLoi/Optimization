from shift_optimizer.scoring import normalize, performance_score, ranking


def test_normalize_basic():
    assert normalize([1, 2, 3]) == [0.0, 0.5, 1.0]


def test_normalize_all_equal_returns_zeros():
    assert normalize([5, 5, 5]) == [0.0, 0.0, 0.0]


def test_performance_score_theo_dominates():
    score = performance_score(theo=[300, 100], hands=[10, 90])
    assert score[0] > score[1]


def test_performance_score_in_unit_range():
    score = performance_score(theo=[50, 120, 400, 90], hands=[30, 60, 20, 75])
    assert all(0.0 <= s <= 1.0 for s in score)


def test_performance_score_missing_gets_median_of_known():
    # 三张有历史 (score 会是 0, 0.5, 1 附近)，第四张无历史 -> 拿中位数
    score = performance_score(theo=[100, 200, 300, None], hands=[100, 200, 300, None])
    known = sorted(score[:3])
    assert known[0] <= score[3] <= known[2]
    assert abs(score[3] - known[1]) < 1e-9          # 恰好是中位数


def test_performance_score_all_missing_returns_zeros():
    assert performance_score(theo=[None, None], hands=[None, None]) == [0.0, 0.0]


def test_ranking_orders_by_score_desc():
    assert ranking([0.1, 0.9, 0.5]) == [3, 1, 2]


def test_ranking_ties_break_by_index():
    assert ranking([0.5, 0.5, 0.9]) == [2, 3, 1]
