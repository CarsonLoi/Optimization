from datetime import date

import pandas as pd
import pytest

from shift_optimizer.io_excel import build_day_fleet, load_config, load_demand


def _write(df, path, sheet):
    df.to_excel(path, sheet_name=sheet, index=False)
    return str(path)


def _demand_row(day, cap=15):
    hc = [f'h{h}' for h in range(24)]
    return pd.DataFrame([[day, *([2] * 24), cap]], columns=['day', *hc, 'capacity'])


# ---------------------------------------------------------------- config

def test_load_config_full(tmp_path):
    df = pd.DataFrame({
        'table': ['A1', 'A2', 'B1'],
        'pod': ['A', 'A', 'B'],
        'preferred_open_hours': [24, 16, 8],
        'theo_per_open_hour': [300, 150, 90],
        'patron_hands_per_hour': [60, 50, 40],
    })
    fleet = load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))

    assert fleet.num_tables == 3
    assert [t.name for t in fleet.tables] == ['A1', 'A2', 'B1']
    assert fleet.has_availability_window is False
    assert fleet.tables[0].pref == 24
    assert fleet.tables[0].theo == 300


def test_load_config_optional_columns_missing(tmp_path):
    df = pd.DataFrame({'table': ['T1', 'T2'], 'pod': ['P', 'P']})
    fleet = load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))
    assert all(t.pref is None and t.theo is None and t.hands is None for t in fleet.tables)


def test_load_config_new_table_blank_stats(tmp_path):
    df = pd.DataFrame({
        'table': ['OLD', 'NEW'], 'pod': ['P', 'P'],
        'theo_per_open_hour': [200, None],
        'patron_hands_per_hour': [50, None],
        'available_from': [None, pd.Timestamp('2026-09-02')],
    })
    fleet = load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))
    assert fleet.has_availability_window is True
    assert fleet.tables[1].theo is None
    assert fleet.tables[1].available_from == date(2026, 9, 2)


def test_load_config_rejects_bad_pref(tmp_path):
    df = pd.DataFrame({'table': ['T1'], 'pod': ['P'], 'preferred_open_hours': [10]})
    with pytest.raises(ValueError):
        load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))


def test_load_config_rejects_duplicate_table_without_window(tmp_path):
    df = pd.DataFrame({'table': ['T1', 'T1'], 'pod': ['P', 'P']})
    with pytest.raises(ValueError):
        load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))


def test_load_config_allows_same_table_non_overlapping_periods(tmp_path):
    # T05 换 pod：P1 到 2026-06-30，之后 P2
    df = pd.DataFrame({
        'table': ['T05', 'T05'], 'pod': ['P1', 'P2'],
        'available_from': [None, pd.Timestamp('2026-07-01')],
        'available_to':   [pd.Timestamp('2026-06-30'), None],
    })
    fleet = load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))
    assert fleet.num_tables == 1
    assert len(fleet.tables) == 2


def test_load_config_rejects_same_table_overlapping_periods(tmp_path):
    df = pd.DataFrame({
        'table': ['T05', 'T05'], 'pod': ['P1', 'P2'],
        'available_from': [None, pd.Timestamp('2026-06-15')],
        'available_to':   [pd.Timestamp('2026-06-30'), None],
    })
    with pytest.raises(ValueError):
        load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))


def test_build_day_fleet_picks_active_period(tmp_path):
    df = pd.DataFrame({
        'table': ['T05', 'T05'], 'pod': ['P1', 'P2'],
        'theo_per_open_hour': [200, 200], 'patron_hands_per_hour': [50, 50],
        'available_from': [None, pd.Timestamp('2026-07-01')],
        'available_to':   [pd.Timestamp('2026-06-30'), None],
    })
    fleet = load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))

    jun = load_demand(_write(_demand_row('2026-06-20'), tmp_path / 'd1.xlsx', 'demand'))[0]
    aug = load_demand(_write(_demand_row('2026-08-20'), tmp_path / 'd2.xlsx', 'demand'))[0]

    assert build_day_fleet(fleet, jun).pod == ['P1']
    assert build_day_fleet(fleet, aug).pod == ['P2']


# ---------------------------------------------------------------- demand

def test_load_demand_basic(tmp_path):
    hc = [f'h{h}' for h in range(24)]
    df = pd.DataFrame([['2026-09-01', *range(24), 15]], columns=['day', *hc, 'capacity'])
    days = load_demand(_write(df, tmp_path / 'd.xlsx', 'demand'))
    assert days[0].label == '2026-09-01'
    assert days[0].the_date == date(2026, 9, 1)
    assert days[0].demand == list(range(24))
    assert days[0].capacity == 15


def test_load_demand_missing_capacity_column(tmp_path):
    hc = [f'h{h}' for h in range(24)]
    df = pd.DataFrame([['D1', *([2] * 24)]], columns=['day', *hc])
    days = load_demand(_write(df, tmp_path / 'd.xlsx', 'demand'))
    assert days[0].capacity is None
    assert days[0].the_date is None


def test_load_demand_wrong_hour_count(tmp_path):
    df = pd.DataFrame([['D1', 1, 2, 3, 10]], columns=['day', 'h0', 'h1', 'h2', 'capacity'])
    with pytest.raises(ValueError):
        load_demand(_write(df, tmp_path / 'd.xlsx', 'demand'))


# ---------------------------------------------------------------- build_day_fleet

def test_build_day_fleet_filters_by_availability(tmp_path):
    df = pd.DataFrame({
        'table': ['OLD', 'MID', 'NEW'], 'pod': ['P', 'P', 'Q'],
        'theo_per_open_hour': [200, 150, None],
        'patron_hands_per_hour': [50, 40, None],
        'available_to':   [pd.Timestamp('2026-09-01'), None, None],
        'available_from': [None, None, pd.Timestamp('2026-09-02')],
    })
    fleet = load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))
    days = load_demand(_write(_demand_row('2026-09-02'), tmp_path / 'd.xlsx', 'demand'))

    dayf = build_day_fleet(fleet, days[0])
    assert dayf.names == ['MID', 'NEW']          # OLD 已停用
    assert dayf.pods == {'P': [0], 'Q': [1]}
    assert dayf.has_history == [True, False]
    # NEW 无历史 -> 拿有历史台(只有 MID)的评分中位数 = MID 的评分
    assert dayf.score[1] == dayf.score[0]


def test_build_day_fleet_requires_date_when_window_present(tmp_path):
    df = pd.DataFrame({'table': ['T1'], 'pod': ['P'],
                       'available_from': [pd.Timestamp('2026-09-01')]})
    fleet = load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))
    days = load_demand(_write(_demand_row('Monday'), tmp_path / 'd.xlsx', 'demand'))
    with pytest.raises(ValueError):
        build_day_fleet(fleet, days[0])
