import pytest

from shift_optimizer.io_excel import DayDemand, FleetConfig
from shift_optimizer.model import pod_penalty_schedule, solve_day
from shift_optimizer.scoring import performance_score, ranking

pytest.importorskip("ortools")


def test_pod_penalty_schedule_size4_matches_original():
    assert pod_penalty_schedule(4) == [0, 30, 2, 30, 0]


def test_pod_penalty_schedule_general_sizes():
    assert pod_penalty_schedule(1) == [0, 0]
    assert pod_penalty_schedule(2) == [0, 30, 0]
    assert pod_penalty_schedule(5) == [0, 30, 2, 2, 30, 0]


def _fleet(names, pod, pref, theo, hands):
    fleet = FleetConfig(names=names, pod=pod, pref=pref, theo=theo, hands=hands)
    for idx, p in enumerate(pod):
        fleet.pods.setdefault(p, []).append(idx)
    fleet.score = performance_score(theo, hands)
    fleet.rank = ranking(fleet.score)
    return fleet


def test_high_performance_table_gets_the_long_shift():
    # 两个单台 pod，除业绩外一切相同。每小时需要 1 张台开着 -> 有一张必须上 24h。
    fleet = _fleet(names=['LOW', 'HIGH'], pod=['P1', 'P2'], pref=[None, None],
                   theo=[100.0, 400.0], hands=[50.0, 50.0])
    day = DayDemand(label='d', demand=[1] * 24, capacity=2)

    res = solve_day(day, fleet, time_limit_s=10)

    assert res.status in ('OPTIMAL', 'FEASIBLE')
    assert res.schedule[1] == 'A'          # 高业绩台拿到 24h 班次
    assert res.schedule[0] == 'G'          # 低业绩台关闭


def test_capacity_is_a_hard_cap():
    fleet = _fleet(names=['T0', 'T1', 'T2', 'T3'], pod=['P'] * 4, pref=[None] * 4,
                   theo=[100.0] * 4, hands=[50.0] * 4)
    demand = [1] * 24
    demand[10] = 4                          # 某小时想要 4 张，但 capacity 只有 2
    day = DayDemand(label='d', demand=demand, capacity=2)

    res = solve_day(day, fleet, time_limit_s=10)

    assert res.status in ('OPTIMAL', 'FEASIBLE')
    assert max(r['tables_open'] for r in res.coverage) <= 2
    assert res.coverage[10]['shortage'] >= 2


def test_infeasible_never_from_high_demand():
    # 需求远超台数也应有解（缺口是软的）
    fleet = _fleet(names=['T0'], pod=['P'], pref=[None], theo=[1.0], hands=[1.0])
    day = DayDemand(label='d', demand=[99] * 24, capacity=None)
    res = solve_day(day, fleet, time_limit_s=10)
    assert res.status in ('OPTIMAL', 'FEASIBLE')
