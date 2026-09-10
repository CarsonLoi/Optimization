"""
建模 + 求解（每天独立一次，只用当天【可用】的台）。

目标函数（最小化）:
    WEIGHT_SHORTAGE * Σ 每小时缺口
  + WEIGHT_SURPLUS  * Σ 每小时过剩
  + Σ pod 拆分罚分                       （AddElement 查表，任意 pod 大小都成立）
  + PREF_WEIGHT     * Σ 人工偏好偏离罚分  （仅对填了 preferred_open_hours 的台）
  - PERF_WEIGHT     * Σ score[台] * 该台开机小时数      （业绩奖励项）

硬约束:
  * 每张台恰好一个班次
  * 每个 pod 最多用 MAX_DISTINCT_SHIFTS_PER_POD 种班次
  * 每小时开台数 <= 当天 capacity

业绩奖励项如何"决定谁上长班次"
------------------------------
覆盖需求 / pod 规则 决定了整体上需要多少张台跑 24h、多少张跑 16h……
在这些约束下，  - Σ score[台] * 开机小时数  这一项会把"开机小时数"尽量
堆到 score 最高的台上（排序不等式）——于是高业绩的台优先拿到长班次。
新台无历史 -> score 取当天有历史台的中位数（既不吃亏也不占便宜）。
"""

from __future__ import annotations

from .config import (
    GAMING_DAY_START_HOUR, HOURS_PER_DAY, MAX_DISTINCT_SHIFTS_PER_POD, NUM_SHIFTS,
    PENALTY_BY_PREF_AND_CATEGORY, PENALTY_PAIRED_SPLIT, PENALTY_UNEVEN_SPLIT,
    PERF_WEIGHT, PREF_WEIGHT, SHIFT_CATEGORY, SHIFT_CODES, SHIFT_COVERS_HOUR,
    SHIFT_OPEN_HOURS, WEIGHT_SHORTAGE, WEIGHT_SURPLUS,
)
from .io_excel import DayDemand, DayFleet, DayResult


def pod_penalty_schedule(pod_size: int) -> list[int]:
    """
    pod 有 pod_size 张台。某班次上有 c 张台时该 (pod, 班次) 的罚分:
        c == 0 或 c == pod_size            -> 0    （整组一起 / 整组都不在）
        少数侧只有 1 张 (min(c, size-c)==1) -> PENALTY_UNEVEN_SPLIT   （落单）
        少数侧 >= 2 张                       -> PENALTY_PAIRED_SPLIT   （对半拆）
    pod_size == 4 时结果是 [0, 30, 2, 30, 0]，与旧脚本一致。
    """
    sched = []
    for c in range(pod_size + 1):
        if c == 0 or c == pod_size:
            sched.append(0)
        elif min(c, pod_size - c) == 1:
            sched.append(PENALTY_UNEVEN_SPLIT)
        else:
            sched.append(PENALTY_PAIRED_SPLIT)
    return sched


def solve_day(day: DayDemand, dayf: DayFleet,
              time_limit_s: float,
              perf_weight: float = PERF_WEIGHT,
              pref_weight: float = PREF_WEIGHT) -> DayResult:
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
    pod_penalty_terms = []
    for pod_name, members in dayf.pods.items():
        size = len(members)
        sched = pod_penalty_schedule(size)
        max_pen = max(sched) if sched else 0
        shift_used = []
        for s in range(NUM_SHIFTS):
            count = model.NewIntVar(0, size, f'pod_{pod_name}_{SHIFT_CODES[s]}_cnt')
            model.Add(count == sum(assign[t, s] for t in members))

            pen = model.NewIntVar(0, max_pen, f'pod_{pod_name}_{SHIFT_CODES[s]}_pen')
            model.AddElement(count, sched, pen)
            pod_penalty_terms.append(pen)

            used = model.NewBoolVar(f'pod_{pod_name}_uses_{SHIFT_CODES[s]}')
            model.Add(count >= 1).OnlyEnforceIf(used)
            model.Add(count == 0).OnlyEnforceIf(used.Not())
            shift_used.append(used)
        model.Add(sum(shift_used) <= MAX_DISTINCT_SHIFTS_PER_POD)

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

    model.Minimize(
        WEIGHT_SHORTAGE * sum(hourly_shortage)
        + WEIGHT_SURPLUS * sum(hourly_surplus)
        + sum(pod_penalty_terms)
        + pref_weight * sum(coeff * charge for charge, coeff in pref_penalty_terms)
        - perf_weight * perf_reward
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
    result.schedule_rows = [{
        'table': dayf.names[t], 'pod': dayf.pod[t],
        'rank': dayf.rank[t], 'score': round(dayf.score[t], 4),
        'has_history': dayf.has_history[t],
        'preferred_open_hours': dayf.pref[t],
        'shift': SHIFT_CODES[s], 'shift_open_hours': SHIFT_OPEN_HOURS[s],
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
