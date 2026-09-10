"""
读/写 Excel。

配置 Excel（默认 config.xlsx，第一个工作表）——列名不分大小写：
    table                  台名/编号（唯一）                       [必填]
    pod                    所属 pod 名/编号                        [必填]
    preferred_open_hours   人工偏好营业时长，24/16/8/0，可留空       [可选]
        别名: preferred_hours / preference / pref / open_hours
    theo_per_open_hour     每营业小时的理论赢数 (Theo)              [可选，缺省 0]
        别名: theo_per_hour / theo
    patron_hands_per_hour  每小时客人手数                           [可选，缺省 0]
        别名: hands_per_hour / patron_hands / hands

需求 Excel（默认 demand.xlsx，第一个工作表）：
    day        当天标签（唯一）
    <24 列>    24 个小时需求，按顺序对应下标 0..23（下标 0 = 07:00）
    capacity   当天"同时开台数"上限，可留空（= 不限制）
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .config import HOURS_PER_DAY, SHIFT_CODES, SHIFT_OPEN_HOURS, VALID_PREF_HOURS
from .scoring import performance_score, ranking


# =====================================================================
# 数据结构
# =====================================================================

@dataclass
class FleetConfig:
    names: list[str]                       # 台名
    pod: list[str]                         # 每张台的 pod 名
    pref: list[int | None]                 # 人工偏好营业时长 (或 None)
    theo: list[float]                      # Theo / 营业小时
    hands: list[float]                     # Patron hands / 小时
    pods: dict[str, list[int]] = field(default_factory=dict)   # pod 名 -> 台下标列表
    score: list[float] = field(default_factory=list)           # 0..1 综合评分
    rank: list[int] = field(default_factory=list)              # 名次 (1=最高)

    @property
    def num_tables(self) -> int:
        return len(self.names)


@dataclass
class DayDemand:
    label: str
    demand: list[int]                      # 长度 24
    capacity: int | None                   # None = 不限制


@dataclass
class DayResult:
    label: str
    status: str
    capacity: int
    objective: float | None = None
    schedule: dict[int, str] | None = None         # 台下标 -> 班次代码
    coverage: list[dict] | None = None             # 每小时一行
    realized_theo: float | None = None             # Σ theo[台] * 该台开机小时数
    realized_hands: float | None = None            # Σ hands[台] * 该台开机小时数


# =====================================================================
# 读取
# =====================================================================

def _norm(name) -> str:
    return str(name).strip().lower().replace(' ', '_')


def _first_alias(columns, aliases):
    return next((a for a in aliases if a in columns), None)


def load_config(path: str) -> FleetConfig:
    df = pd.read_excel(path, sheet_name=0)
    df.columns = [_norm(c) for c in df.columns]

    if 'table' not in df.columns or 'pod' not in df.columns:
        raise ValueError(f"配置 Excel 需要列 table 和 pod；实际读到: {list(df.columns)}")

    pref_col  = _first_alias(df.columns, ['preferred_open_hours', 'preferred_hours',
                                          'preference', 'pref', 'open_hours'])
    theo_col  = _first_alias(df.columns, ['theo_per_open_hour', 'theo_per_hour', 'theo'])
    hands_col = _first_alias(df.columns, ['patron_hands_per_hour', 'hands_per_hour',
                                          'patron_hands', 'hands'])

    df = df[df['table'].notna()].copy()
    names = [str(v).strip() for v in df['table']]
    pod   = [str(v).strip() for v in df['pod']]

    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"配置 Excel 里有重复的 table 名: {dupes}")

    # 偏好营业时长（可选、逐行可留空）
    pref: list[int | None] = []
    for raw in (df[pref_col] if pref_col else [None] * len(df)):
        if raw is None or (isinstance(raw, float) and pd.isna(raw)) or pd.isna(raw):
            pref.append(None)
            continue
        hours = int(round(float(raw)))
        if hours not in VALID_PREF_HOURS:
            raise ValueError(f"preferred_open_hours 必须是 {sorted(VALID_PREF_HOURS)} 之一，读到 {hours}")
        pref.append(hours)

    def _num_col(col, label):
        if col is None:
            print(f"  [提示] 配置里没有 {label} 列，全部按 0 处理（该项不参与排名）。")
            return [0.0] * len(df)
        out = []
        for raw in df[col]:
            out.append(0.0 if pd.isna(raw) else float(raw))
        return out

    theo  = _num_col(theo_col, 'Theo per open hour')
    hands = _num_col(hands_col, 'Patron hands per hour')

    fleet = FleetConfig(names=names, pod=pod, pref=pref, theo=theo, hands=hands)

    for idx, pod_name in enumerate(pod):
        fleet.pods.setdefault(pod_name, []).append(idx)

    fleet.score = performance_score(theo, hands)
    fleet.rank = ranking(fleet.score)
    return fleet


def load_demand(path: str) -> list[DayDemand]:
    df = pd.read_excel(path, sheet_name=0)
    df.columns = [_norm(c) for c in df.columns]

    if 'day' not in df.columns:
        raise ValueError(f"需求 Excel 需要一列 day；实际读到: {list(df.columns)}")
    cap_col = 'capacity' if 'capacity' in df.columns else None

    hour_cols = [c for c in df.columns if c not in ('day', cap_col)]
    if len(hour_cols) != HOURS_PER_DAY:
        raise ValueError(
            f"需求 Excel 除 day/capacity 外应正好有 24 个小时列，实际 {len(hour_cols)}: {hour_cols}"
        )

    df = df[df['day'].notna()].copy()
    days: list[DayDemand] = []
    for _, row in df.iterrows():
        label = row['day']
        label = str(label.date()) if isinstance(label, pd.Timestamp) else str(label).strip()

        demand = [0 if pd.isna(row[c]) else int(round(float(row[c]))) for c in hour_cols]
        if any(d < 0 for d in demand):
            raise ValueError(f"{label}: 需求出现负数")

        if cap_col is None or pd.isna(row[cap_col]):
            capacity = None
        else:
            capacity = int(round(float(row[cap_col])))
            if capacity < 0:
                raise ValueError(f"{label}: capacity 为负数")

        days.append(DayDemand(label=label, demand=demand, capacity=capacity))

    if len({d.label for d in days}) != len(days):
        raise ValueError("需求 Excel 里有重复的 day 标签")
    return days


# =====================================================================
# 写出
# =====================================================================

def write_excel(out_path: str, results: list[DayResult], fleet: FleetConfig) -> None:
    fleet_rows = [{
        'table': fleet.names[t], 'pod': fleet.pod[t],
        'preferred_open_hours': fleet.pref[t],
        'theo_per_open_hour': fleet.theo[t],
        'patron_hands_per_hour': fleet.hands[t],
        'score': round(fleet.score[t], 4),
        'rank': fleet.rank[t],
    } for t in range(fleet.num_tables)]

    schedule_rows, coverage_rows, summary_rows = [], [], []
    for res in results:
        infeasible = res.schedule is None
        summary_rows.append({
            'day': res.label, 'status': res.status, 'capacity': res.capacity,
            'objective': res.objective,
            'total_shortage': None if infeasible else sum(r['shortage'] for r in res.coverage),
            'total_surplus':  None if infeasible else sum(r['surplus'] for r in res.coverage),
            'realized_theo': res.realized_theo,
            'realized_hands': res.realized_hands,
        })
        if infeasible:
            continue
        for t in range(fleet.num_tables):
            code = res.schedule[t]
            schedule_rows.append({
                'day': res.label, 'table': fleet.names[t], 'pod': fleet.pod[t],
                'rank': fleet.rank[t], 'score': round(fleet.score[t], 4),
                'preferred_open_hours': fleet.pref[t],
                'shift': code,
                'shift_open_hours': SHIFT_OPEN_HOURS[SHIFT_CODES.index(code)],
            })
        for row in res.coverage:
            coverage_rows.append({'day': res.label, **row})

    def _df(rows, cols):
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)

    with pd.ExcelWriter(out_path, engine='openpyxl') as xw:
        _df(summary_rows, ['day', 'status', 'capacity', 'objective', 'total_shortage',
                           'total_surplus', 'realized_theo', 'realized_hands']).to_excel(
            xw, sheet_name='summary', index=False)
        _df(fleet_rows, list(fleet_rows[0]) if fleet_rows else []).to_excel(
            xw, sheet_name='fleet', index=False)
        _df(schedule_rows, ['day', 'table', 'pod', 'rank', 'score',
                            'preferred_open_hours', 'shift', 'shift_open_hours']).to_excel(
            xw, sheet_name='schedules', index=False)
        _df(coverage_rows, ['day', 'hour_index', 'clock', 'demand', 'capacity',
                            'tables_open', 'shortage', 'surplus']).to_excel(
            xw, sheet_name='coverage', index=False)
