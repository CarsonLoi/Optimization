import pytest

from shift_optimizer.io_excel import DayDemand, DayFleet
from shift_optimizer.model import pod_penalty_schedule, solve_day
from shift_optimizer.scoring import performance_score, ranking

pytest.importorskip("ortools")


def test_pod_penalty_schedule_only_punishes_avoidable_loneliness():
    # 只罚"1 张台孤零零落在另一边、且本可避免"（min(c,size-c)==1 且 size>=4）；
    # 只要没有台落单，不管拆成几比几都不罚。
    assert pod_penalty_schedule(4) == [0, 30, 0, 30, 0]        # 1+3 罚；2+2 不罚
    assert pod_penalty_schedule(5) == [0, 30, 0, 0, 30, 0]     # 1+4 罚；2+3 不罚
    assert pod_penalty_schedule(6) == [0, 30, 0, 0, 0, 30, 0]  # 只罚 1+5；2+4、3+3 都不罚


def test_pod_penalty_schedule_small_pods_never_punished():
    # 1/2/3 张台的 pod：落单是没法避免的（唯一能做的拆法本身就带着"少数侧=1"），不该罚
    assert pod_penalty_schedule(1) == [0, 0]
    assert pod_penalty_schedule(2) == [0, 0, 0]     # 唯一拆法 1+1，其实是完全对半
    assert pod_penalty_schedule(3) == [0, 0, 0, 0]  # 唯一拆法 1+2，3 张台能做到的最公平拆分


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


def test_soft_split_discount_can_make_a_lonely_soft_split_worth_it():
    # 一个 4 张台的 pod。需求形状是: H 的窗口(idx5..12)要 1 张台，L 的窗口(idx13..20)要 3 张台。
    # 折扣关着时，"1 张落单"要付 30 分基准罚分，模型宁可选一个 2+2（比如 C+L，覆盖没那么
    # 精确但不落单）；折扣拉到 1.0 后，H+L 这个"1+3 但完全贴合需求、又衔接得上"的拆法
    # 把 30 分基准罚分整个退掉，变成比任何 2+2 都便宜，模型应该换过去。
    demand = [0] * 5 + [1] * 8 + [3] * 8 + [0] * 3
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
    assert 'H' not in no_discount.schedule.values() or 'L' not in no_discount.schedule.values() \
        or sorted(no_discount.schedule.values()) != ['H', 'L', 'L', 'L']   # 折扣关着，不该选 1+3

    assert full_discount.status in ('OPTIMAL', 'FEASIBLE')
    assert sorted(full_discount.schedule.values()) == ['H', 'L', 'L', 'L']  # 折扣打开，换成 1+3
    assert all(row['pod_split_soft'] for row in full_discount.schedule_rows)

    # 打开折扣让模型换到一个覆盖完全贴合需求的拆法，总分不该比关着折扣更差
    assert full_discount.objective < no_discount.objective


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
