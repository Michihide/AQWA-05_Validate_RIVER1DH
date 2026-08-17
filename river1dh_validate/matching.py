"""WIS観測所とRIVER1DHソルバーの断面点 (river_point.gpkg) のマッチング。

マッチング方針 (実データで検証済み):
  1. 観測所の河川名 (river_name) と river_point.gpkg の「河川名」列が完全一致する
     行だけに候補を絞る。
  2. 観測所の緯度経度 (WGS84) を river_point.gpkg のCRS (通常EPSG:6671等の平面
     直角座標系) に再投影し、絞り込んだ候補の中から最近傍点を採用する。

「1河川名に複数候補があることは構造上ないはず」という前提のため、
`build_river_name_to_code_map` は河川名が複数の河川コード (W05_002) に
またがっている場合、フォールバックせず即座にエラーを送出する。これは
個別の観測所単位ではなく、GPKG全体に対して一度だけ行うグローバルな健全性
チェックである。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

RIVER_NAME_COL = "河川名"
RIVER_CODE_COL = "W05_002"
KP_COL = "KP"
IID_COL = "i_ID"


class AmbiguousRiverNameError(RuntimeError):
    """1つの河川名が複数の河川コードに対応している場合に送出する。

    データ構造上、1つの河川名は1つの河川コードにのみ対応するはずであり、
    これが崩れている場合はマッチングの前提が壊れているため、静かに
    フォールバックするのではなく処理全体を止める。
    """


@dataclass
class WisStation:
    station_id: str
    station_name: str
    river_name: str
    water_system: str
    lat: Optional[float]
    lon: Optional[float]
    gauge_zero_m: Optional[float]
    is_active: bool
    flood_watch_level_m: Optional[float] = None
    flood_advisory_level_m: Optional[float] = None
    evacuation_judgment_level_m: Optional[float] = None
    flood_danger_level_m: Optional[float] = None
    design_high_water_level_m: Optional[float] = None

    def reference_water_levels_tp(self) -> list[tuple[str, float]]:
        """観測所メタデータのレベル水位 (零点高基準) を T.P. 標高に変換して返す。"""
        if self.gauge_zero_m is None:
            return []
        levels: list[tuple[str, float]] = []
        specs = (
            ("水防団待機", self.flood_watch_level_m),
            ("氾濫注意", self.flood_advisory_level_m),
            ("避難判断", self.evacuation_judgment_level_m),
            ("氾濫危険", self.flood_danger_level_m),
            ("計画高水位", self.design_high_water_level_m),
        )
        for label, rel_m in specs:
            if rel_m is None:
                continue
            levels.append((label, self.gauge_zero_m + rel_m))
        return levels


@dataclass
class MatchResult:
    station: WisStation
    matched: bool
    reason: str = ""  # matched=False の場合の理由
    river_code: Optional[str] = None
    kp: Optional[float] = None
    i_id: Optional[int] = None
    x: Optional[float] = None
    y: Optional[float] = None
    distance_m: Optional[float] = None  # 最も近い断面点までの距離 (未マッチでも診断用に保持)


def build_river_name_to_code_map(river_points: gpd.GeoDataFrame) -> dict:
    """河川名 -> 河川コード (W05_002) の対応表を作る。

    1つの河川名が複数の河川コードに対応している場合は
    `AmbiguousRiverNameError` を送出する (構造上あってはならないケース)。
    """
    grouped = river_points.groupby(RIVER_NAME_COL)[RIVER_CODE_COL].unique()
    ambiguous = {name: list(codes) for name, codes in grouped.items() if len(codes) > 1}
    if ambiguous:
        detail = ", ".join(f"{name}={codes}" for name, codes in ambiguous.items())
        raise AmbiguousRiverNameError(
            "river_point.gpkg 内で、1つの河川名が複数の河川コードに対応しています"
            f" (データ構造上あってはならない状態です): {detail}"
        )
    return {name: codes[0] for name, codes in grouped.items()}


def match_station(
    station: WisStation,
    river_points: gpd.GeoDataFrame,
    name_to_code: dict,
    max_distance_m: float,
) -> MatchResult:
    """`max_distance_m` はハードな足切り閾値。これを超える最近傍点しか無い場合は
    「マッチ無し」として扱う (=対象の断面点の半径 `max_distance_m` 以内に観測所が
    無いケースを除外する)。"""
    if station.lat is None or station.lon is None:
        return MatchResult(station=station, matched=False, reason="no_coordinates")

    if station.river_name not in name_to_code:
        return MatchResult(station=station, matched=False, reason="river_not_in_network")

    candidates = river_points[river_points[RIVER_NAME_COL] == station.river_name]

    station_point = gpd.GeoSeries(
        [Point(station.lon, station.lat)], crs="EPSG:4326"
    ).to_crs(river_points.crs)
    station_xy = station_point.iloc[0]

    distances = candidates.geometry.distance(station_xy)
    nearest_idx = distances.idxmin()
    nearest = candidates.loc[nearest_idx]
    distance_m = float(distances.loc[nearest_idx])

    if distance_m > max_distance_m:
        return MatchResult(
            station=station,
            matched=False,
            reason="no_cross_section_within_max_distance",
            distance_m=distance_m,
        )

    return MatchResult(
        station=station,
        matched=True,
        river_code=str(nearest[RIVER_CODE_COL]),
        kp=float(nearest[KP_COL]),
        i_id=int(nearest[IID_COL]),
        x=float(nearest.geometry.x),
        y=float(nearest.geometry.y),
        distance_m=distance_m,
    )


def match_all(
    stations: list,
    river_points: gpd.GeoDataFrame,
    max_distance_m: float,
) -> list:
    """全観測所をマッチングする。曖昧な河川名があれば最初に例外を送出する。"""
    name_to_code = build_river_name_to_code_map(river_points)
    return [
        match_station(station, river_points, name_to_code, max_distance_m)
        for station in stations
    ]


def results_to_frames(results: list) -> tuple:
    """マッチ結果を (matched_df, unmatched_df) の2つの DataFrame に分ける。"""
    matched_rows = []
    unmatched_rows = []
    for r in results:
        if r.matched:
            matched_rows.append(
                {
                    "station_id": r.station.station_id,
                    "station_name": r.station.station_name,
                    "river_name": r.station.river_name,
                    "river_code": r.river_code,
                    "kp": r.kp,
                    "i_id": r.i_id,
                    "x": r.x,
                    "y": r.y,
                    "distance_m": r.distance_m,
                }
            )
        else:
            unmatched_rows.append(
                {
                    "station_id": r.station.station_id,
                    "station_name": r.station.station_name,
                    "river_name": r.station.river_name,
                    "reason": r.reason,
                    # river_not_in_network / no_coordinates の場合はNone。
                    # no_cross_section_within_max_distance の場合は、実際に見つかった
                    # 最近傍点までの距離 (足切りされた理由の確認用)。
                    "nearest_distance_m": r.distance_m,
                }
            )
    matched_df = pd.DataFrame(matched_rows)
    unmatched_df = pd.DataFrame(unmatched_rows)
    return matched_df, unmatched_df
