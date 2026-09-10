"""
生成示例输入 Excel:  data/config.xlsx  和  data/demand.xlsx

    python scripts/make_templates.py

- 台/pod/偏好 = 旧脚本的写死数据；另加 Theo/Hands 业绩列（历史数据）。
- 演示可用期：T00 在 2026-09-02 起停用；T19 是 2026-09-02 才上的新台（无历史）。
- demand 三天。
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
DEMAND = {
    '2026-09-01': [4, 4, 5, 4, 6, 10, 9, 12, 11, 10, 13, 9, 9, 12, 16, 18, 15, 16, 16, 17, 15, 11, 6, 4],
    '2026-09-02': [3, 3, 4, 4, 5, 8, 9, 10, 10, 11, 12, 10, 10, 13, 15, 17, 16, 15, 14, 15, 13, 10, 7, 5],
    '2026-09-03': [4, 4, 4, 5, 6, 9, 10, 11, 12, 11, 12, 10, 11, 13, 16, 18, 17, 16, 15, 16, 14, 11, 7, 5],
}
CAPACITY = {'2026-09-01': 20, '2026-09-02': 18, '2026-09-03': 20}

rng = np.random.default_rng(7)
pod_of = {t: name for name, members in POD_MEMBERS.items() for t in members}
theo = [int(v) for v in rng.normal(loc=[120 + 6 * h for h in PREF], scale=40).clip(40, 500)]
hands = [int(v) for v in rng.normal(loc=55, scale=12, size=20).clip(20, 90)]

rows = []
for t in range(20):
    row = {
        'table': f'T{t:02d}', 'pod': pod_of[t], 'preferred_open_hours': PREF[t],
        'theo_per_open_hour': theo[t], 'patron_hands_per_hour': hands[t],
        'available_from': None, 'available_to': None,
    }
    if t == 0:                       # T00: 2026-09-02 起停用
        row['available_to'] = pd.Timestamp('2026-09-01')
    if t == 19:                      # T19: 2026-09-02 才上的新台，无历史
        row['available_from'] = pd.Timestamp('2026-09-02')
        row['theo_per_open_hour'] = None
        row['patron_hands_per_hour'] = None
    rows.append(row)

pd.DataFrame(rows).to_excel(DATA / 'config.xlsx', sheet_name='tables', index=False)

hour_cols = [f'h{h}' for h in range(24)]        # h0 = 07:00 那一格
demand_df = pd.DataFrame(
    [[day, *DEMAND[day], CAPACITY[day]] for day in DEMAND],
    columns=['day', *hour_cols, 'capacity'],
)
demand_df.to_excel(DATA / 'demand.xlsx', sheet_name='demand', index=False)

print(f"已生成 {DATA / 'config.xlsx'}")
print(f"已生成 {DATA / 'demand.xlsx'}")
