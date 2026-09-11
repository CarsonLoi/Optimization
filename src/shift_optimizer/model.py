"""
建模 + 求解（每天独立一次，只用当天【可用】的台）。

目标函数（最小化）:
    WEIGHT_SHORTAGE     * Σ 每小时缺口
  + WEIGHT_SURPLUS      * Σ 每小时过剩
  + Σ pod 拆分基准罚分                       （AddElement 查表，任意 pod 大小都成立）
  - SOFT_SPLIT_DISCOUNT * Σ pod "衔接得上"时退回的那部分罚分  （见下）
  + PREF_WEIGHT         * Σ 人工偏好偏离罚分  （仅对填了 preferred_open_hours 的台）
  - PERF_WEIGHT         * Σ score[台] * 该台开机小时数            （业绩奖励项：决定"哪个时长"）
  - WINDOW_WEIGHT       * Σ score[台] * desirability[该台选的班次] （窗口奖励项：决定"同时长选哪个窗口"）

硬约束:
  * 每张台恰好一个班次
  * 每个 pod 最多用 MAX_DISTINCT_SHIFTS_PER_POD 种班次
  * 每小时开台数 <= 当天 capacity

pod 拆分罚分：只罚"可以避免的落单" + 衔接顺不顺
--------------------------------------------------
pod_penalty_schedule(pod_size) 只罚"1 张台孤零零落在另一个班次上，而这本来可以
避免"这一种情况（min(c, pod_size-c) == 1 且 pod_size >= 4）；只要没有台落单
（少数侧 >= 2 张），不管拆成几比几都不罚——6 张台的 pod 拆成 2+4 或 3+3 都完全
不罚，只有 1+5 才罚。pod_size <= 3 时任何拆分都不罚，因为落单在那个大小下根本
没法避免（见函数注释）。

在这基础上，如果一个 pod 恰好拆成了 SOFT_SHIFT_PAIRS 里"共用一个开/关钟点"
的那种班次组合（比如 H 12:00-20:00 接 L 20:00-04:00，交班干干净净、没有缝隙），
就退回 SOFT_SPLIT_DISCOUNT 比例的罚分；两个班次的钟点完全对不上（比如 C 和 J），
就不打折，按基准罚分全额计。

业绩奖励项如何"决定谁上长班次"
------------------------------
覆盖需求 / pod 规则 决定了整体上需要多少张台跑 24h、多少张跑 16h……
在这些约束下，  - Σ score[台] * 开机小时数  这一项会把"开机小时数"尽量
堆到 score 最高的台上（排序不等式）——于是高业绩的台优先拿到长班次。
新台无历史 -> score 取当天有历史台的中位数（既不吃亏也不占便宜）。

窗口奖励项如何"决定同时长选哪个窗口"
------------------------------------
16h 有 C/E 两个窗口、8h 有 H/L/J/N 四个窗口，时长相同但覆盖的钟点不同。
desirability[班次] = 该班次覆盖的小时里，当天需求之和，在【同一时长类别内】
做 min-max 归一化到 0..1（24h 只有 A、关闭只有 G，没得选，恒为 0）。
当覆盖约束允许"同时长、选哪个窗口都一样"时，这一项把需求覆盖更多的窗口
让给 score 更高的台；覆盖不是真的无所谓时，覆盖项（权重大得多）仍然说了算。
"""

from __future__ import annotations

from .config import (
    GAMING_DAY_START_HOUR, HOURS_PER_DAY, MAX_DISTINCT_SHIFTS_PER_POD, NUM_SHIFTS,
    PENALTY_BY_PREF_AND_CATEGORY, PENALTY_UNEVEN_SPLIT,
    PERF_WEIGHT, PREF_WEIGHT, SHIFT_CATEGORY, SHIFT_CODES, SHIFT_COVERS_HOUR,
    SHIFT_OPEN_HOURS, SOFT_SHIFT_PAIRS, SOFT_SPLIT_DISCOUNT, WEIGHT_SHORTAGE,
    WEIGHT_SURPLUS, WINDOW_WEIGHT,
)
from .io_excel import DayDemand, DayFleet, DayResult
from .scoring import normalize


def window_desirability(demand: list[int]) -> list[float]:
    """
    每个班次在【自己所属时长类别】内的"窗口吸引力"，0..1。
    = 该班次覆盖的小时里，当天需求之和，在同类别班次间 min-max 归一化。
    类别里只有一个班次的（24h 的 A、关闭的 G）没有可比对象，恒为 0。
    """
    demand_covered = [sum(demand[h] * int(SHIFT_COVERS_HOUR[s, h]) for h in range(HOURS_PER_DAY))
                      for s in range(NUM_SHIFTS)]
    result = [0.0] * NUM_SHIFTS
    for category in set(SHIFT_CATEGORY):
        members = [s for s in range(NUM_SHIFTS) if SHIFT_CATEGORY[s] == category]
        if len(members) < 2:
            continue                                         # 没得选，desirability 恒 0
        for s, v in zip(members, normalize([demand_covered[s] for s in members])):
            result[s] = v
    return result


def pod_penalty_schedule(pod_size: int) -> list[int]:
    """
    pod 有 pod_size 张台。某班次上有 c 张台时该 (pod, 班次) 的罚分。

    只罚"把 1 张台孤零零地落在别的班次上，而这本来是可以避免的"这一种情况；
    只要没有台落单（少数侧 >= 2 张），不管拆成几比几都不罚：
        c == 0 / pod_size                     -> 0   （整组一起，或整组都不在这个班次）
        min(c, pod_size-c) == 1 且 pod_size>=4 -> PENALTY_UNEVEN_SPLIT   （真落单，且本可避免）
        其余（min(c,pod_size-c) >= 2，或 pod_size<=3）-> 0

    pod_size <= 3 时任何拆分都不罚：1/2 张台没有"另一半"可言，3 张台唯一能做的拆分
    (1+2) 本身就是 3 张台能做到的最公平拆分（min=1，但没有 min>=2 的替代方案），
    落单是没法避免的，不该罚。pod_size >= 4 起，min==1 就是可以避免的落单
    （比如 6 张台本可以 2+4 或 3+3，1+5 是自己选的），才罚。

    例：pod_size=4 -> [0,30,0,30,0]（只罚 1+3，2+2 完全不罚）；
        pod_size=6 -> [0,30,0,0,0,30,0]（只罚 1+5，2+4、3+3 都不罚）。
    """
    sched = []
    for c in range(pod_size + 1):
        if c == 0 or c == pod_size:
            sched.append(0)
        elif min(c, pod_size - c) == 1 and pod_size >= 4:
            sched.append(PENALTY_UNEVEN_SPLIT)
        else:
            sched.append(0)
    return sched


def solve_day(day: DayDemand, dayf: DayFleet,
              time_limit_s: float,
              perf_weight: float = PERF_WEIGHT,
              pref_weight: float = PREF_WEIGHT,
              window_weight: float = WINDOW_WEIGHT,
              soft_split_discount: float = SOFT_SPLIT_DISCOUNT) -> DayResult:
    from ortools.sat.python import cp_model

    T = dayf.num_tables
    capacity = T if day.capacity is None else day.capacity
    demand = day.demand

    result = DayResult(label=day.label, status='NO_TABLES', capacity=capacity,
                       num_available=T)
    if T == 0:
        return result

    model = cp_model.CpModel()

    # ---- 决策变量: assign[t, s] == 1  ->  台 t 选班次 s ----
    assign = {(t, s): model.NewBoolVar(f'assign_t{t}_{SHIFT_CODES[s]}')
              for t in range(T) for s in range(NUM_SHIFTS)}
    for t in range(T):
        model.AddExactlyOne(assign[t, s] for s in range(NUM_SHIFTS))

    open_hours = {t: sum(assign[t, s] * SHIFT_OPEN_HOURS[s] for s in range(NUM_SHIFTS))
                  for t in range(T)}

    # ---- 约束 A: pod 整齐度 ----
    # 每个 pod 的拆分罚分先按 pod_penalty_schedule 算出"基准"（跟哪两个具体班次无关）。
    # 如果这个 pod 恰好拆成了【共用一个开/关钟点】的两个班次（SOFT_SHIFT_PAIRS 里的一对，
    # 比如 H+L 首尾相接），就退回 soft_split_discount 比例的罚分——同样是拆分，交班顺的
    # 拆法比"完全对不上"的拆法罚得轻。
    pod_penalty_terms = []      # 基准罚分（未打折），沿用旧版，始终计入
    pod_discount_terms = []     # 命中"衔接得上"时可退回的那一部分（按 soft_split_discount 扣）
    pod_is_soft_split = {}      # pod 名 -> 是否命中"衔接得上"（求解后读出来，写进输出表）
    for pod_name, members in dayf.pods.items():
        size = len(members)
        sched = pod_penalty_schedule(size)
        max_pen = max(sched) if sched else 0
        shift_used = []
        pod_pens = []
        for s in range(NUM_SHIFTS):
            count = model.NewIntVar(0, size, f'pod_{pod_name}_{SHIFT_CODES[s]}_cnt')
            model.Add(count == sum(assign[t, s] for t in members))

            pen = model.NewIntVar(0, max_pen, f'pod_{pod_name}_{SHIFT_CODES[s]}_pen')
            model.AddElement(count, sched, pen)
            pod_penalty_terms.append(pen)
            pod_pens.append(pen)

            used = model.NewBoolVar(f'pod_{pod_name}_uses_{SHIFT_CODES[s]}')
            model.Add(count >= 1).OnlyEnforceIf(used)
            model.Add(count == 0).OnlyEnforceIf(used.Not())
            shift_used.append(used)
        model.Add(sum(shift_used) <= MAX_DISTINCT_SHIFTS_PER_POD)

        # 这个 pod 实际用到的两个班次，是不是 SOFT_SHIFT_PAIRS 里衔接得上的那一对？
        pair_flags = []
        for s1, s2 in SOFT_SHIFT_PAIRS:
            both = model.NewBoolVar(f'pod_{pod_name}_soft_{SHIFT_CODES[s1]}{SHIFT_CODES[s2]}')
            model.AddBoolAnd([shift_used[s1], shift_used[s2]]).OnlyEnforceIf(both)
            model.AddBoolOr([shift_used[s1].Not(), shift_used[s2].Not()]).OnlyEnforceIf(both.Not())
            pair_flags.append(both)

        is_soft_split = model.NewBoolVar(f'pod_{pod_name}_is_soft_split')
        model.AddBoolOr(pair_flags).OnlyEnforceIf(is_soft_split)
        model.AddBoolAnd([f.Not() for f in pair_flags]).OnlyEnforceIf(is_soft_split.Not())

        discount_amount = model.NewIntVar(0, 2 * max_pen, f'pod_{pod_name}_discount_amt')
        model.Add(discount_amount == sum(pod_pens)).OnlyEnforceIf(is_soft_split)
        model.Add(discount_amount == 0).OnlyEnforceIf(is_soft_split.Not())
        pod_discount_terms.append(discount_amount)
        pod_is_soft_split[pod_name] = is_soft_split

    # ---- 约束 B: 人工偏好营业时长（仅对填了 pref 的台）----
    pref_penalty_terms = []                                  # list[(charge_bool, coeff)]
    for t in range(T):
        if dayf.pref[t] is None:
            continue
        pref = dayf.pref[t]
        is_cat = [model.NewBoolVar(f't{t}_cat{c}') for c in range(4)]
        for c in range(4):
            model.Add(is_cat[c] == sum(assign[t, s] for s in range(NUM_SHIFTS)
                                       if SHIFT_CATEGORY[s] == c))
        model.AddExactlyOne(is_cat)                          # 逻辑上多余，留作自检
        for c in range(4):
            charge = model.NewBoolVar(f't{t}_devcharge_cat{c}')
            model.AddBoolOr([is_cat[c], charge])
            pref_penalty_terms.append((charge, PENALTY_BY_PREF_AND_CATEGORY[pref][c]))

    # ---- 约束 C: 逐小时覆盖 + capacity ----
    hourly_shortage, hourly_surplus = [], []
    for h in range(HOURS_PER_DAY):
        tables_open = sum(assign[t, s] * int(SHIFT_COVERS_HOUR[s, h])
                          for t in range(T) for s in range(NUM_SHIFTS))
        model.Add(tables_open <= capacity)

        shortage = model.NewIntVar(0, int(demand[h]), f'short_h{h}')
        surplus = model.NewIntVar(0, T, f'surp_h{h}')
        model.Add(tables_open - int(demand[h]) == surplus - shortage)
        hourly_shortage.append(shortage)
        hourly_surplus.append(surplus)

    perf_reward = sum(dayf.score[t] * open_hours[t] for t in range(T))

    desir = window_desirability(demand)
    window_reward = sum(dayf.score[t] * desir[s] * assign[t, s]
                        for t in range(T) for s in range(NUM_SHIFTS))

    model.Minimize(
        WEIGHT_SHORTAGE * sum(hourly_shortage)
        + WEIGHT_SURPLUS * sum(hourly_surplus)
        + sum(pod_penalty_terms)
        - soft_split_discount * sum(pod_discount_terms)
        + pref_weight * sum(coeff * charge for charge, coeff in pref_penalty_terms)
        - perf_weight * perf_reward
        - window_weight * window_reward
    )

    # ---- 求解 ----
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.random_seed = 42
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    result.status = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return result

    result.objective = round(solver.ObjectiveValue(), 2)
    chosen = {t: s for t in range(T) for s in range(NUM_SHIFTS)
              if solver.BooleanValue(assign[t, s])}
    result.schedule = {dayf.names[t]: SHIFT_CODES[s] for t, s in chosen.items()}
    pod_soft_split = {name: bool(solver.BooleanValue(var))
                      for name, var in pod_is_soft_split.items()}
    result.schedule_rows = [{
        'table': dayf.names[t], 'pod': dayf.pod[t],
        'rank': dayf.rank[t], 'score': round(dayf.score[t], 4),
        'has_history': dayf.has_history[t],
        'preferred_open_hours': dayf.pref[t],
        'shift': SHIFT_CODES[s], 'shift_open_hours': SHIFT_OPEN_HOURS[s],
        'window_desirability': round(desir[s], 4),
        'pod_split_soft': pod_soft_split[dayf.pod[t]],
    } for t, s in sorted(chosen.items(), key=lambda kv: dayf.rank[kv[0]])]

    result.realized_theo = round(sum((dayf.theo[t] or 0.0) * SHIFT_OPEN_HOURS[s]
                                     for t, s in chosen.items()), 1)
    result.realized_hands = round(sum((dayf.hands[t] or 0.0) * SHIFT_OPEN_HOURS[s]
                                      for t, s in chosen.items()), 1)

    coverage = []
    for h in range(HOURS_PER_DAY):
        opened = sum(int(SHIFT_COVERS_HOUR[s, h]) for s in chosen.values())
        coverage.append({
            'hour_index': h,
            'clock': f"{(GAMING_DAY_START_HOUR + h) % 24:02d}:00",
            'demand': int(demand[h]),
            'capacity': capacity,
            'tables_open': opened,
            'shortage': max(0, int(demand[h]) - opened),
            'surplus': max(0, opened - int(demand[h])),
        })
    result.coverage = coverage
    return result
