"""
命令行入口。

    shift-optimizer --config data/config.xlsx --demand data/demand.xlsx --out schedule_output.xlsx
    python -m shift_optimizer ...
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .config import DEFAULT_TIME_LIMIT_S, PERF_WEIGHT, PREF_WEIGHT
from .io_excel import DayResult, build_day_fleet, load_config, load_demand, write_excel
from .model import solve_day


def _print_day(res: DayResult) -> None:
    print(f"\n============  {res.label}  (status={res.status}, "
          f"可用台={res.num_available}, capacity={res.capacity}, objective={res.objective})  ============")
    if res.schedule is None:
        print("  （无可用台或无可行解）")
        return
    print(f"  当日实现 Theo={res.realized_theo}  Patron hands={res.realized_hands}")

    print("  名次  台        pod   历史  偏好  评分   班次")
    for r in res.schedule_rows:
        pref = '-' if r['preferred_open_hours'] is None else f"{r['preferred_open_hours']:>2}h"
        hist = '有' if r['has_history'] else '新台'
        print(f"   {r['rank']:3d}  {r['table']:>8}  {r['pod']:>4}  {hist:>3}  "
              f"{pref:>4}  {r['score']:.3f}  {r['shift']}")

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
                    help='配置 Excel (table / pod / preferred_open_hours / theo / hands / available_from / available_to)')
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

    print(f"读到 {fleet.num_tables} 张台（master），{len(days)} 天。"
          f"{'按 available_from/to 逐日过滤。' if fleet.has_availability_window else ''}")
    print(f"权重: shortage/surplus 固定, perf={args.perf_weight}, pref={args.pref_weight}")

    results = []
    for day in days:
        dayf = build_day_fleet(fleet, day)
        res = solve_day(day, dayf, args.time_limit,
                        perf_weight=args.perf_weight, pref_weight=args.pref_weight)
        _print_day(res)
        results.append(res)

    write_excel(args.out, results, fleet)
    print(f"\n已写入 {args.out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
