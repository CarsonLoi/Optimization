"""
读/写 Excel。

配置 Excel（默认 data/config.xlsx，第一个工作表）——每张台一行，列名不分大小写：
    table                  台名/编号（唯一）                        [必填]
    pod                    所属 pod 名/编号                         [必填]
    preferred_open_hours   人工偏好营业时长，24/16/8/0，可留空        [可选]
        别名: preferred_hours / preference / pref / open_hours
    theo_per_open_hour     每营业小时理论赢数 (Theo)，历史数据        [可选]
        别名: theo_per_hour / theo               留空 = 新台、无历史
    patron_hands_per_hour  每小时客人手数，历史数据                   [可选]
        别名: hands_per_hour / patron_hands / hands
    available_from         该台生效日期（含），留空 = 一直有效         [可选]
        别名: start_date / valid_from
    available_to           该台失效日期（含），留空 = 一直有效         [可选]
        别名: end_date / valid_to

    某一天求解时，只把  available_from <= 当天 <= available_to  的台纳入。
    完全不写这两列 -> 所有台每天都在。

需求 Excel（默认 data/demand.xlsx，第一个工作表）：
    day        当天标签，最好是日期（用于按 available_from/to 过滤台）
    <24 列>    24 个小时需求，按顺序对应下标 0..23（下标 0 = 07:00）
    capacity   当天"同时开台数"上限，可留空（= 不限制）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from .config import HOURS_PER_DAY, SHIFT_CODES, SHIFT_OPEN_HOURS, VALID_PREF_HOURS
from .scoring import performance_score, ranking


# =====================================================================
# 数据结构
# =====================================================================

@dataclass
class TableInfo:
    name: str
    pod: str
    pref: int | None
    theo: float | None                    # None = 无历史
    hands: float | None                   # None = 无历史
    available_from: date | None
    available_to: date | None

    def available_on(self, d: date | None) -> bool:
        if d is None:                     # 需求那天没有可解析的日期 -> 当作全部可用
            return True
        if self.available_from and d < self.available_from:
            return False
        if self.available_to and d > self.available_to:
            return False
        return True


@dataclass
class FleetConfig:
    tables: list[TableInfo]
    has_availability_window: bool = False   # config 里是否出现了 available_from/to 列

    @property
    def num_tables(self) -> int:
        return len(self.tables)


@dataclass
class DayFleet:
    """某一天【可用台】的子集，评分/排名在这个子集内重新计算。"""
    names: list[str]
    pod: list[str]
    pref: list[int | None]
    theo: list[float | None]
    hands: list[float | None]
    pods: dict[str, list[int]] = field(default_factory=dict)   # pod 名 -> 局部下标
    score: list[float] = field(default_factory=list)           # 0..1
    rank: list[int] = field(default_factory=list)
    has_history: list[bool] = field(default_factory=list)

    @property
    def num_tables(self) -> int:
        return len(self.names)


@dataclass
class DayDemand:
    label: str
    the_date: date | None
    demand: list[int]                      # 长度 24
    capacity: int | None                   # None = 不限制


@dataclass
class DayResult:
    label: str
    status: str
    capacity: int
    num_available: int
    objective: float | None = None
    schedule: dict[str, str] | None = None           # 台名 -> 班次代码
    schedule_rows: list[dict] | None = None          # 供 schedules 工作表
    coverage: list[dict] | None = None
    realized_theo: float | None = None
    realized_hands: float | None = None


# =====================================================================
# 读取
# =====================================================================

def _norm(name) -> str:
    return str(name).strip().lower().replace(' ', '_')


def _first_alias(columns, aliases):
    return next((a for a in aliases if a in columns), None)


def _to_date(raw) -> date | None:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or pd.isna(raw):
        return None
    ts = pd.to_datetime(raw, errors='coerce')
    if pd.isna(ts):
        raise ValueError(f"无法解析为日期: {raw!r}")
    return ts.date()


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
    from_col  = _first_alias(df.columns, ['available_from', 'start_date', 'valid_from'])
    to_col    = _first_alias(df.columns, ['available_to', 'end_date', 'valid_to'])

    df = df[df['table'].notna()].copy()
    names = [str(v).strip() for v in df['table']]
    if len(set(names)) != len(names):
        dupes = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(f"配置 Excel 里有重复的 table 名: {dupes}")

    def _opt_pref(raw):
        if raw is None or pd.isna(raw):
            return None
        hours = int(round(float(raw)))
        if hours not in VALID_PREF_HOURS:
            raise ValueError(f"preferred_open_hours 必须是 {sorted(VALID_PREF_HOURS)} 之一，读到 {hours}")
        return hours

    def _opt_num(raw):
        return None if (raw is None or pd.isna(raw)) else float(raw)

    tables: list[TableInfo] = []
    for i, (_, row) in enumerate(df.iterrows()):
        tables.append(TableInfo(
            name=names[i],
            pod=str(row['pod']).strip(),
            pref=_opt_pref(row[pref_col]) if pref_col else None,
            theo=_opt_num(row[theo_col]) if theo_col else None,
            hands=_opt_num(row[hands_col]) if hands_col else None,
            available_from=_to_date(row[from_col]) if from_col else None,
            available_to=_to_date(row[to_col]) if to_col else None,
        ))

    return FleetConfig(tables=tables, has_availability_window=bool(from_col or to_col))


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
        raw = row['day']
        ts = pd.to_datetime(raw, errors='coerce')
        the_date = None if pd.isna(ts) else ts.date()
        label = str(the_date) if the_date is not None else str(raw).strip()

        demand = [0 if pd.isna(row[c]) else int(round(float(row[c]))) for c in hour_cols]
        if any(d < 0 for d in demand):
            raise ValueError(f"{label}: 需求出现负数")

        if cap_col is None or pd.isna(row[cap_col]):
            capacity = None
        else:
            capacity = int(round(float(row[cap_col])))
            if capacity < 0:
                raise ValueError(f"{label}: capacity 为负数")

        days.append(DayDemand(label=label, the_date=the_date, demand=demand, capacity=capacity))

    if len({d.label for d in days}) != len(days):
        raise ValueError("需求 Excel 里有重复的 day 标签")
    return days


# =====================================================================
# 按天组装可用台
# =====================================================================

def build_day_fleet(fleet: FleetConfig, day: DayDemand) -> DayFleet:
    if fleet.has_availability_window and day.the_date is None:
        raise ValueError(
            f"config 里有 available_from/to，但需求里的 day='{day.label}' 不是日期，无法按日期过滤。"
        )

    avail = [t for t in fleet.tables if t.available_on(day.the_date)]

    dayf = DayFleet(
        names=[t.name for t in avail],
        pod=[t.pod for t in avail],
        pref=[t.pref for t in avail],
        theo=[t.theo for t in avail],
        hands=[t.hands for t in avail],
        has_history=[t.theo is not None and t.hands is not None for t in avail],
    )
    for idx, pod_name in enumerate(dayf.pod):
        dayf.pods.setdefault(pod_name, []).append(idx)
    dayf.score = performance_score(dayf.theo, dayf.hands)
    dayf.rank = ranking(dayf.score)
    return dayf


# =====================================================================
# 写出
# =====================================================================

def write_excel(out_path: str, results: list[DayResult], fleet: FleetConfig) -> None:
    fleet_rows = [{
        'table': t.name, 'pod': t.pod,
        'preferred_open_hours': t.pref,
        'theo_per_open_hour': t.theo,
        'patron_hands_per_hour': t.hands,
        'has_history': t.theo is not None and t.hands is not None,
        'available_from': t.available_from,
        'available_to': t.available_to,
    } for t in fleet.tables]

    summary_rows, schedule_rows, coverage_rows = [], [], []
    for res in results:
        infeasible = res.schedule is None
        summary_rows.append({
            'day': res.label, 'status': res.status,
            'tables_available': res.num_available, 'capacity': res.capacity,
            'objective': res.objective,
            'total_shortage': None if infeasible else sum(r['shortage'] for r in res.coverage),
            'total_surplus':  None if infeasible else sum(r['surplus'] for r in res.coverage),
            'realized_theo': res.realized_theo,
            'realized_hands': res.realized_hands,
        })
        if infeasible:
            continue
        for r in res.schedule_rows:
            schedule_rows.append({'day': res.label, **r})
        for row in res.coverage:
            coverage_rows.append({'day': res.label, **row})

    def _df(rows, cols):
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=cols)

    with pd.ExcelWriter(out_path, engine='openpyxl') as xw:
        _df(summary_rows, ['day', 'status', 'tables_available', 'capacity', 'objective',
                           'total_shortage', 'total_surplus',
                           'realized_theo', 'realized_hands']).to_excel(
            xw, sheet_name='summary', index=False)
        _df(fleet_rows, list(fleet_rows[0]) if fleet_rows else []).to_excel(
            xw, sheet_name='fleet', index=False)
        _df(schedule_rows, ['day', 'table', 'pod', 'rank', 'score', 'has_history',
                            'preferred_open_hours', 'shift', 'shift_open_hours']).to_excel(
            xw, sheet_name='schedules', index=False)
        _df(coverage_rows, ['day', 'hour_index', 'clock', 'demand', 'capacity',
                            'tables_open', 'shortage', 'surplus']).to_excel(
            xw, sheet_name='coverage', index=False)
