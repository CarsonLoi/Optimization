"""
生成示例输入 Excel:  data/config.xlsx  和  data/demand.xlsx

    python scripts/make_templates.py

台/pod/偏好 = 旧脚本的写死数据；另加 Theo/Hands 业绩列 + 第二天需求做演示。
"""

from pathlib import Path

import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parent.parent / 'data'
DATA.mkdir(exist_ok=True)

POD_MEMBERS = {
    'P0': [0, 1, 2, 3], 'P1': [4, 5, 6, 7], 'P2': [8, 9, 10, 11],
    'P3': [12, 13, 14, 15], 'P4': [16, 17, 18, 19],
}
PREF = [24, 24, 24, 24, 16, 24, 24, 16, 16, 16, 16, 16, 8, 8, 8, 8, 0, 8, 8, 0]
DEMAND_DAY1 = [4, 4, 5, 4, 6, 10, 9, 12, 11, 10, 13, 9,
               9, 12, 16, 18, 15, 16, 16, 17, 15, 11, 6, 4]
DEMAND_DAY2 = [3, 3, 4, 4, 5, 8, 9, 10, 10, 11, 12, 10,
               10, 13, 15, 17, 16, 15, 14, 15, 13, 10, 7, 5]

rng = np.random.default_rng(7)
pod_of = {t: name for name, members in POD_MEMBERS.items() for t in members}

config = pd.DataFrame({
    'table': [f'T{t:02d}' for t in range(20)],
    'pod': [pod_of[t] for t in range(20)],
    'preferred_open_hours': PREF,
    # Theo / 营业小时（美元）：跟偏好时长略正相关（高价值台通常是 24h 台）
    'theo_per_open_hour': [int(v) for v in rng.normal(
        loc=[120 + 6 * h for h in PREF], scale=40).clip(40, 500)],
    # 每小时客人手数
    'patron_hands_per_hour': [int(v) for v in rng.normal(loc=55, scale=12, size=20).clip(20, 90)],
})
config.to_excel(DATA / 'config.xlsx', sheet_name='tables', index=False)

hour_cols = [f'h{h}' for h in range(24)]        # h0 = 07:00 那一格
demand = pd.DataFrame(
    [['2026-09-01', *DEMAND_DAY1, 20],
     ['2026-09-02', *DEMAND_DAY2, 18]],
    columns=['day', *hour_cols, 'capacity'],
)
demand.to_excel(DATA / 'demand.xlsx', sheet_name='demand', index=False)

print(f"已生成 {DATA / 'config.xlsx'}")
print(f"已生成 {DATA / 'demand.xlsx'}")
