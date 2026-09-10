import pandas as pd
import pytest

from shift_optimizer.io_excel import load_config, load_demand


def _write(df, path, sheet):
    df.to_excel(path, sheet_name=sheet, index=False)
    return str(path)


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
    assert fleet.names == ['A1', 'A2', 'B1']
    assert fleet.pods == {'A': [0, 1], 'B': [2]}
    assert fleet.pref == [24, 16, 8]
    # A1 有最高 Theo 和 Hands -> 评分最高 -> rank 1
    assert fleet.rank[0] == 1
    assert fleet.score[0] == max(fleet.score)


def test_load_config_optional_columns_missing(tmp_path):
    df = pd.DataFrame({'table': ['T1', 'T2'], 'pod': ['P', 'P']})
    fleet = load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))
    assert fleet.pref == [None, None]
    assert fleet.theo == [0.0, 0.0]
    assert fleet.hands == [0.0, 0.0]
    assert fleet.score == [0.0, 0.0]


def test_load_config_blank_pref_row(tmp_path):
    df = pd.DataFrame({
        'table': ['T1', 'T2'], 'pod': ['P', 'P'],
        'pref': [24, None],
    })
    fleet = load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))
    assert fleet.pref == [24, None]


def test_load_config_rejects_bad_pref(tmp_path):
    df = pd.DataFrame({'table': ['T1'], 'pod': ['P'], 'preferred_open_hours': [10]})
    with pytest.raises(ValueError):
        load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))


def test_load_config_rejects_duplicate_table(tmp_path):
    df = pd.DataFrame({'table': ['T1', 'T1'], 'pod': ['P', 'P']})
    with pytest.raises(ValueError):
        load_config(_write(df, tmp_path / 'c.xlsx', 'tables'))


def test_load_demand_basic(tmp_path):
    hc = [f'h{h}' for h in range(24)]
    df = pd.DataFrame([['D1', *range(24), 15]], columns=['day', *hc, 'capacity'])
    days = load_demand(_write(df, tmp_path / 'd.xlsx', 'demand'))
    assert len(days) == 1
    assert days[0].label == 'D1'
    assert days[0].demand == list(range(24))
    assert days[0].capacity == 15


def test_load_demand_missing_capacity_column(tmp_path):
    hc = [f'h{h}' for h in range(24)]
    df = pd.DataFrame([['D1', *([2] * 24)]], columns=['day', *hc])
    days = load_demand(_write(df, tmp_path / 'd.xlsx', 'demand'))
    assert days[0].capacity is None


def test_load_demand_wrong_hour_count(tmp_path):
    df = pd.DataFrame([['D1', 1, 2, 3, 10]], columns=['day', 'h0', 'h1', 'h2', 'capacity'])
    with pytest.raises(ValueError):
        load_demand(_write(df, tmp_path / 'd.xlsx', 'demand'))
