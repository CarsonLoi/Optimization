"""
命令行入口。

    shift-optimizer --config config.xlsx --demand demand.xlsx --out schedule_output.xlsx
    python -m shift_optimizer ...
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import DEFAULT_TIME_LIMIT_S, PERF_WEIGHT, PREF_WEIGHT
from .io_excel import FleetConfig, DayResult, load_config, load_demand, write_excel
from .model import solve_day


def _print_day(res: DayResult, fleet: FleetConfig) -> None:
    print(f"\n============  {res.label}  (status={res.status}, "
          f"capacity={res.capacity}, objective={res.objective})  ============")
    if res.schedule is None:
        print("  找不到可行解。")
        return
    print(f"  当日实现 Theo={res.realized_theo}  Patron hands={res.realized_hands}")

    print("  名次  台        pod   偏好  评分   班次")
    order = sorted(range(fleet.num_tables), key=lambda t: fleet.rank[t])
    for t in order:
        pref = '-' if fleet.pref[t] is None else f"{fleet.pref[t]:>2}h"
        print(f"   {fleet.rank[t]:3d}  {fleet.names[t]:>8}  {fleet.pod[t]:>4}  "
              f"{pref:>4}  {fleet.score[t]:.3f}  {res.schedule[t]}")

    print("  下标  时钟   需求  容量  开台   缺口  过剩")
    for row in res.coverage:
        flag = "  <-- 缺口" if row['shortage'] > 0 else ""
        print(f"    {row['hour_index']:2d}   {row['clock']}  {row['demand']:4d}  "
              f"{row['capacity']:4d}  {row['tables_open']:4d}  "
              f"{row['shortage']:4d}  {row['surplus']:4d}{flag}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog='shift-optimizer',
                                 description="赌台逐日班次分配 (OR-Tools CP-SAT)")
    ap.add_argument('--config', default='data/config.xlsx',
                    help='配置 Excel (table / pod / preferred_open_hours / theo / hands)')
    ap.add_argument('--demand', default='data/demand.xlsx',
                    help='需求 Excel (day / 24 小时列 / capacity)')
    ap.add_argument('--out', default='schedule_output.xlsx', help='输出 Excel 路径')
    ap.add_argument('--time-limit', type=float, default=DEFAULT_TIME_LIMIT_S,
                    help='每天求解秒数上限')
    ap.add_argument('--perf-weight', type=float, default=PERF_WEIGHT,
                    help='业绩奖励项权重（大 = 更看重把长班次给高业绩的台）')
    ap.add_argument('--pref-weight', type=float, default=PREF_WEIGHT,
                    help='人工偏好项权重（0 = 完全忽略 preferred_open_hours）')
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    for p in (args.config, args.demand):
        if not Path(p).is_file():
            raise SystemExit(f"找不到文件: {p}")

    fleet = load_config(args.config)
    days = load_demand(args.demand)

    print(f"读到 {fleet.num_tables} 张台、{len(fleet.pods)} 个 pod、{len(days)} 天。")
    print("pod 组成: " + ", ".join(f"{k}({len(v)})" for k, v in fleet.pods.items()))
    print(f"权重: shortage/surplus 固定, perf={args.perf_weight}, pref={args.pref_weight}")

    results = []
    for day in days:
        res = solve_day(day, fleet, args.time_limit,
                        perf_weight=args.perf_weight, pref_weight=args.pref_weight)
        _print_day(res, fleet)
        results.append(res)

    write_excel(args.out, results, fleet)
    print(f"\n已写入 {args.out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
