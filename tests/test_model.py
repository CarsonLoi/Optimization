import pytest

from shift_optimizer.io_excel import DayDemand, DayFleet
from shift_optimizer.model import pod_penalty_schedule, solve_day
from shift_optimizer.scoring import performance_score, ranking

pytest.importorskip("ortools")


def test_pod_penalty_schedule_size4_matches_original():
    assert pod_penalty_schedule(4) == [0, 30, 2, 30, 0]


def test_pod_penalty_schedule_general_sizes():
    assert pod_penalty_schedule(1) == [0, 0]
    assert pod_penalty_schedule(2) == [0, 30, 0]
    assert pod_penalty_schedule(5) == [0, 30, 2, 2, 30, 0]


def _dayfleet(names, pod, pref, theo, hands):
    dayf = DayFleet(names=names, pod=pod, pref=pref, theo=theo, hands=hands,
                    has_history=[t is not None and h is not None
                                 for t, h in zip(theo, hands)])
    for idx, p in enumerate(pod):
        dayf.pods.setdefault(p, []).append(idx)
    dayf.score = performance_score(theo, hands)
    dayf.rank = ranking(dayf.score)
    return dayf


def test_high_performance_table_gets_the_long_shift():
    dayf = _dayfleet(names=['LOW', 'HIGH'], pod=['P1', 'P2'], pref=[None, None],
                     theo=[100.0, 400.0], hands=[50.0, 50.0])
    day = DayDemand(label='d', the_date=None, demand=[1] * 24, capacity=2)

    res = solve_day(day, dayf, time_limit_s=10)

    assert res.status in ('OPTIMAL', 'FEASIBLE')
    assert res.schedule['HIGH'] == 'A'
    assert res.schedule['LOW'] == 'G'


def test_capacity_is_a_hard_cap():
    dayf = _dayfleet(names=[f'T{i}' for i in range(4)], pod=['P'] * 4, pref=[None] * 4,
                     theo=[100.0] * 4, hands=[50.0] * 4)
    demand = [1] * 24
    demand[10] = 4
    day = DayDemand(label='d', the_date=None, demand=demand, capacity=2)

    res = solve_day(day, dayf, time_limit_s=10)

    assert res.status in ('OPTIMAL', 'FEASIBLE')
    assert max(r['tables_open'] for r in res.coverage) <= 2
    assert res.coverage[10]['shortage'] >= 2


def test_no_available_tables_returns_gracefully():
    dayf = _dayfleet(names=[], pod=[], pref=[], theo=[], hands=[])
    day = DayDemand(label='d', the_date=None, demand=[1] * 24, capacity=None)
    res = solve_day(day, dayf, time_limit_s=5)
    assert res.status == 'NO_TABLES'
    assert res.schedule is None


def test_window_order_gives_more_desirable_window_to_higher_score():
    # 需求只出现在两个不重叠的 8h 窗口 H(下标5..12) 和 L(下标13..20)，L 那段需求更高。
    # capacity=1 禁止两张台挤在同一个窗口；{H,L} 组合比任何其它 8h 窗口对都便宜得多，
    # 所以两张台必然一个上 H、一个上 L —— 到底谁上哪个，覆盖成本完全打平（可互换），
    # 只由 window 奖励项决定：desirability(L) > desirability(H)，应该给评分更高的台。
    demand = [0] * 5 + [1] * 8 + [2] * 8 + [0] * 3
    assert len(demand) == 24
    dayf = _dayfleet(names=['LOW', 'HIGH'], pod=['P1', 'P2'], pref=[8, 8],
                     theo=[100.0, 400.0], hands=[50.0, 50.0])
    day = DayDemand(label='d', the_date=None, demand=demand, capacity=1)

    # perf_weight=0、极大 pref_weight：把两张台钉死在 8h 类别里，
    # 排除"干脆用一张 16h 的 C 覆盖全段"这个会跟 H+L 打平的替代方案，
    # 这样待检验的 window_weight 就是唯一起作用的区分项。
    res = solve_day(day, dayf, time_limit_s=10,
                    perf_weight=0.0, pref_weight=1000.0, window_weight=0.05)

    assert res.status in ('OPTIMAL', 'FEASIBLE')
    assert {res.schedule['LOW'], res.schedule['HIGH']} == {'H', 'L'}
    assert res.schedule['HIGH'] == 'L'
    assert res.schedule['LOW'] == 'H'


def test_window_weight_zero_leaves_window_choice_to_coverage_only():
    # window_weight=0 时，这个模型不再看评分——只是确认它照常求解，不报错。
    demand = [0] * 5 + [1] * 8 + [2] * 8 + [0] * 3
    dayf = _dayfleet(names=['LOW', 'HIGH'], pod=['P1', 'P2'], pref=[8, 8],
                     theo=[100.0, 400.0], hands=[50.0, 50.0])
    day = DayDemand(label='d', the_date=None, demand=demand, capacity=1)

    res = solve_day(day, dayf, time_limit_s=10,
                    perf_weight=0.0, pref_weight=1000.0, window_weight=0.0)

    assert res.status in ('OPTIMAL', 'FEASIBLE')
    assert {res.schedule['LOW'], res.schedule['HIGH']} == {'H', 'L'}


def test_infeasible_never_from_high_demand():
    dayf = _dayfleet(names=['T0'], pod=['P'], pref=[None], theo=[1.0], hands=[1.0])
    day = DayDemand(label='d', the_date=None, demand=[99] * 24, capacity=None)
    res = solve_day(day, dayf, time_limit_s=10)
    assert res.status in ('OPTIMAL', 'FEASIBLE')
