"""Download_WIS の出力 (観測所メタデータ + 観測所ごとの時系列CSV) の読み込み。"""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from .matching import WisStation

STATIONS_CSV_NAME = "water_level_discharge_stations.csv"
TIMESERIES_SUBDIR = "timeseries"
TIMESERIES_DISCHARGE_SUBDIR = "timeseries_discharge"


def _to_float(text: str) -> Optional[float]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def load_stations(wis_output_dir: Path, water_system: str) -> list:
    """`water_level_discharge_stations.csv` から指定の水系の観測所一覧を読む。

    `is_active` は問わない (廃止観測所でもイベント当時のデータがあれば比較対象になりうる)。
    """
    path = wis_output_dir / STATIONS_CSV_NAME
    stations = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("water_system") != water_system:
                continue
            stations.append(
                WisStation(
                    station_id=row["station_id"],
                    station_name=row["station_name"],
                    river_name=row["river_name"],
                    water_system=row["water_system"],
                    lat=_to_float(row.get("latitude_wgs84", "")),
                    lon=_to_float(row.get("longitude_wgs84", "")),
                    gauge_zero_m=_to_float(row.get("detail_gauge_zero_m", "")),
                    is_active=(row.get("is_active", "").strip().upper() == "TRUE"),
                )
            )
    return stations


def load_observed_series(
    wis_output_dir: Path,
    station: WisStation,
    start: datetime,
    end: datetime,
) -> pd.Series:
    """観測所の時系列CSVを読み、[start, end] にクリップし、TP標高に変換したSeriesを返す。

    欠測フラグ等で `water_level_m` が空の行は除外する。`gauge_zero_m` が
    不明な観測所は変換できないため空のSeriesを返す (呼び出し側でスキップ判定する)。
    """
    path = wis_output_dir / TIMESERIES_SUBDIR / f"{station.station_id}.csv"
    if not path.exists() or station.gauge_zero_m is None:
        return pd.Series(dtype=float, name="obs_value")

    df = pd.read_csv(path, encoding="utf-8", usecols=["datetime", "water_level_m"])
    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y-%m-%d %H:%M")
    df = df[(df["datetime"] >= start) & (df["datetime"] <= end)]
    df["water_level_m"] = pd.to_numeric(df["water_level_m"], errors="coerce")
    df = df[df["water_level_m"].notna()]
    if df.empty:
        return pd.Series(dtype=float, name="obs_value")

    df["obs_value"] = df["water_level_m"] + station.gauge_zero_m
    series = df.set_index("datetime")["obs_value"]
    series.name = "obs_value"
    return series


def load_observed_discharge_series(
    wis_output_dir: Path,
    station: WisStation,
    start: datetime,
    end: datetime,
) -> pd.Series:
    """観測所の時刻流量CSV (`--timeseries-discharge` の出力) を読み、
    [start, end] にクリップした Series を返す。

    水位と異なり、流量は零点高による標高変換が不要なため `discharge_m3s`
    の値をそのまま使う。時刻流量が一切登録されていない観測所はファイルが
    存在しないため、その場合は空の Series を返す (呼び出し側でスキップ判定する)。
    """
    path = wis_output_dir / TIMESERIES_DISCHARGE_SUBDIR / f"{station.station_id}.csv"
    if not path.exists():
        return pd.Series(dtype=float, name="obs_value")

    df = pd.read_csv(path, encoding="utf-8", usecols=["datetime", "discharge_m3s"])
    df["datetime"] = pd.to_datetime(df["datetime"], format="%Y-%m-%d %H:%M")
    df = df[(df["datetime"] >= start) & (df["datetime"] <= end)]
    df["discharge_m3s"] = pd.to_numeric(df["discharge_m3s"], errors="coerce")
    df = df[df["discharge_m3s"].notna()]
    if df.empty:
        return pd.Series(dtype=float, name="obs_value")

    series = df.set_index("datetime")["discharge_m3s"]
    series.name = "obs_value"
    return series
