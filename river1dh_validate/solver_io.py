"""RIVER1DHソルバーの出力 (wide-format CSV + river_point.gpkg) の読み込み。

`timeseries_of_waterlevel_river1dh.csv` のようなソルバー出力CSVは、
1行目に対応する `river_point.gpkg` への相対パスが書かれており、2行目が
ヘッダ (`TIME` + 断面点 `i_ID` のリスト)、3行目以降がデータ、という
共通フォーマットを持つ (`04_Visualization` 配下のスクリプト群と同じ規約)。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys

import geopandas as gpd
import pandas as pd

_VIZ = Path(__file__).resolve().parents[2] / "04_Visualization"
if str(_VIZ) not in sys.path:
    sys.path.insert(0, str(_VIZ))
from result_archive import has_river_archive, read_river_points, read_river_timeseries


def read_gpkg_path(csv_path: Path) -> Path:
    """CSVの1行目に書かれている river_point.gpkg への相対パスを解決する。"""
    with open(csv_path, encoding="utf-8") as f:
        first_line = f.readline().strip()
    gpkg_path = (csv_path.parent / first_line).resolve()
    if not gpkg_path.exists():
        raise FileNotFoundError(
            f"{csv_path} の1行目に書かれた river_point.gpkg が見つかりません: {gpkg_path}"
        )
    return gpkg_path


def load_river_points(csv_path: Path) -> gpd.GeoDataFrame:
    if csv_path.exists():
        gpkg_path = read_gpkg_path(csv_path)
        return gpd.read_file(gpkg_path)
    points = read_river_points(csv_path.parent)
    if points is None:
        raise FileNotFoundError(f"river_point を CSV / GPKG.zip から読めません: {csv_path.parent}")
    return points


def load_timeseries_csv(csv_path: Path) -> pd.DataFrame:
    """`TIME` 列をJSTの壁時計時刻 (`time_jst`) に変換したDataFrameを返す。

    `timeseries_of_waterlevel_river1dh.csv` と `timeseries_of_discharge_river1dh.csv`
    はどちらも同一フォーマット (1行目gpkgパス、2行目以降 TIME + i_ID 列) の
    ため、この読み込み処理自体は変量によらず共通で使える。

    AQWA自身の可視化スクリプト (`04_Visualization/riv1d_longitudinal.py`) と
    同じ規約 (`datetime.utcfromtimestamp(TIME)`) に従う。これは実データで
    検証済みで、Input.txt に指定された開始/終了日時 (JSTのつもりで書かれた
    日時) とズレなく一致する (=UTC変換関数を使っているが中身はJSTの壁時計
    時刻として書き出されている)。
    """
    if csv_path.exists():
        df = pd.read_csv(csv_path, skiprows=1)
    else:
        df = read_river_timeseries(csv_path.parent, csv_path.name)
        if df is None:
            raise FileNotFoundError(f"時系列を CSV / GPKG.zip から読めません: {csv_path}")
    df["time_jst"] = df["TIME"].apply(datetime.utcfromtimestamp)
    return df


def load_waterlevel_timeseries(csv_path: Path) -> pd.DataFrame:
    return load_timeseries_csv(csv_path)


def load_discharge_timeseries(csv_path: Path) -> pd.DataFrame:
    return load_timeseries_csv(csv_path)


def series_for_i_id(df: pd.DataFrame, i_id: int) -> pd.Series:
    """指定した i_ID 列の時系列を `time_jst` をインデックスにして返す。"""
    col = next((c for c in (str(i_id), i_id) if c in df.columns), None)
    if col is None:
        try:
            col = next(c for c in df.columns if c != "TIME" and c != "time_jst" and int(c) == int(i_id))
        except StopIteration:
            raise KeyError(f"i_ID={i_id} に対応する列がタイムシリーズCSVにありません") from None
    series = df.set_index("time_jst")[col]
    series.name = "sim_value"
    return series
