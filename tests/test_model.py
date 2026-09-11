import pytest

from shift_optimizer.io_excel import DayDemand, DayFleet
from shift_optimizer.model import pod_penalty_schedule, solve_day
from shift_optimizer.scoring import performance_score, ranking

pytest.importorskip("ortools")


def test_pod_penalty_schedule_size4_matches_original():
    assert pod_penalty_schedule(4) == [0, 30, 2, 30, 0]


def test_pod_penalty_schedule_size5_unchanged():
    assert pod_penalty_schedule(5) == [0, 30, 2, 2, 30, 0]


def test_pod_penalty_schedule_fairness_fix_for_odd_and_small_pods():
    # 2 张台唯一的拆法 1+1 其实是完全对半（差距 0）——只该罚"对半"那一档，不是"落单"
    assert pod_penalty_schedule(2) == [0, 2, 0]
    # 3 张台唯一的拆法 1+2 已经是 3 张台能做到的最公平拆分（差距 1）——同样只罚"对半"那一档，
    # 不该跟 4 张台的 1+3（差距 2，真的偏）一样重罚
    assert pod_penalty_schedule(3) == [0, 2, 2, 0]
    assert pod_penalty_schedule(1) == [0, 0]


def test_pod_penalty_schedule_scales_with_size():
    # 6 张台：3+3(差0,最公平)=2；2+4(差2)=跟 4-pod 的最差档同分=30；1+5(差4)=比 30 更狠
    assert pod_penalty_schedule(6) == [0, 58, 30, 2, 30, 58, 0]
    # 7 张台：3+4(差1,最公平)=2；2+5(差3)=30；1+6(差5)=58
    assert pod_penalty_schedule(7) == [0, 58, 30, 2, 2, 30, 58, 0]


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


def test_soft_split_discount_refunds_pod_penalty_for_compatible_pair():
    # 一个 4 张台的 pod，需求形状让它 2+2 拆最划算，覆盖成本相同的候选拆法里正好有
    # H(12:00-20:00)+L(20:00-04:00)——两者首尾相接，是 SOFT_SHIFT_PAIRS 里的一对，
    # 同时也有覆盖成本相同但配不上钟点的候选（比如全押 16h 的 C + 另外两张关闭）。
    # 折扣=0 时这些候选打平（都是 4 分的基准拆分罚分）；折扣拉到 1.0 后，
    # 只有 H+L 能把这 4 分整个退回去，变成严格最优，逼着模型选它。
    demand = [0] * 5 + [2] * 8 + [2] * 8 + [0] * 3
    assert len(demand) == 24
    dayf = _dayfleet(names=[f'T{i}' for i in range(4)], pod=['P'] * 4, pref=[None] * 4,
                     theo=[100.0] * 4, hands=[50.0] * 4)
    day = DayDemand(label='d', the_date=None, demand=demand, capacity=None)

    no_discount = solve_day(day, dayf, time_limit_s=10,
                            perf_weight=0.0, pref_weight=0.0, window_weight=0.0,
                            soft_split_discount=0.0)
    full_discount = solve_day(day, dayf, time_limit_s=10,
                              perf_weight=0.0, pref_weight=0.0, window_weight=0.0,
                              soft_split_discount=1.0)

    assert no_discount.status in ('OPTIMAL', 'FEASIBLE')
    assert no_discount.objective == pytest.approx(4.0)     # 基准 2+2 拆分罚分，折扣关着不退

    assert full_discount.status in ('OPTIMAL', 'FEASIBLE')
    assert sorted(full_discount.schedule.values()) == ['H', 'H', 'L', 'L']
    assert all(row['pod_split_soft'] for row in full_discount.schedule_rows)
    assert full_discount.objective == pytest.approx(0.0)   # 4 分基准罚分被 1.0 折扣整个退回


def test_soft_split_discount_does_not_apply_to_a_mismatched_pair():
    # 同一个 pod，逼着它拆成对不上钟点的一对：把 4 张台的偏好钉死在 16h（大 pref_weight），
    # 16h 类别里只有 C(12:00-04:00) 和 E(15:00-07:00) 两个选项，二者不共用任何开/关钟点
    # （不在 SOFT_SHIFT_PAIRS 里）。需求只落在 C 独有的早段(idx5..7)和 E 独有的晚段(idx21..23)，
    # 逼出 2+2 的 C/E 拆分（覆盖成本明显比"全押 C"或"全押 E"更低，见下方断言前的验证）。
    demand = [0] * 5 + [2] * 3 + [0] * 13 + [2] * 3
    assert len(demand) == 24
    dayf = _dayfleet(names=[f'T{i}' for i in range(4)], pod=['P'] * 4, pref=[16] * 4,
                     theo=[100.0] * 4, hands=[50.0] * 4)
    day = DayDemand(label='d', the_date=None, demand=demand, capacity=None)

    no_discount = solve_day(day, dayf, time_limit_s=10,
                            perf_weight=0.0, pref_weight=1000.0, window_weight=0.0,
                            soft_split_discount=0.0)
    full_discount = solve_day(day, dayf, time_limit_s=10,
                              perf_weight=0.0, pref_weight=1000.0, window_weight=0.0,
                              soft_split_discount=1.0)

    for res in (no_discount, full_discount):
        assert res.status in ('OPTIMAL', 'FEASIBLE')
        assert sorted(res.schedule.values()) == ['C', 'C', 'E', 'E']
        assert not any(row['pod_split_soft'] for row in res.schedule_rows)

    # C/E 对不上钟点 -> 没有折扣可退，两种 soft_split_discount 结果完全一样
    assert no_discount.objective == pytest.approx(full_discount.objective)


def test_infeasible_never_from_high_demand():
    dayf = _dayfleet(names=['T0'], pod=['P'], pref=[None], theo=[1.0], hands=[1.0])
    day = DayDemand(label='d', the_date=None, demand=[99] * 24, capacity=None)
    res = solve_day(day, dayf, time_limit_s=10)
    assert res.status in ('OPTIMAL', 'FEASIBLE')
