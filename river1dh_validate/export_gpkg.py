"""マッチした WIS 観測所と対応断面点を GeoPackage に書き出す。"""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from .matching import MatchResult


def export_matched_stations_gpkg(
    matched_results: list[MatchResult],
    metrics_df: pd.DataFrame,
    output_path: Path,
    section_crs,
) -> Path:
    """比較にマッチした観測所を GPKG 出力する。

    レイヤ:
      - ``wis_stations``: WIS メタデータ上の観測所位置 (EPSG:4326)
      - ``matched_cross_sections``: マッチした river_point 断面点 (section_crs)
    """
    if not matched_results:
        raise ValueError("マッチした観測所がありません")

    metrics_by_id = {}
    if not metrics_df.empty and "station_id" in metrics_df.columns:
        metrics_by_id = metrics_df.set_index("station_id").to_dict("index")

    wis_rows = []
    section_rows = []

    for r in matched_results:
        st = r.station
        m = metrics_by_id.get(st.station_id, {})
        n_points = m.get("n_points")
        used = bool(n_points) if pd.notna(n_points) else False

        base = {
            "station_id": st.station_id,
            "station_name": st.station_name,
            "river_name": st.river_name,
            "water_system": st.water_system,
            "river_code": r.river_code,
            "kp": r.kp,
            "i_id": r.i_id,
            "match_dist_m": r.distance_m,
            "gauge_zero_m": st.gauge_zero_m,
            "n_points": n_points if pd.notna(n_points) else None,
            "used_in_cmp": used,
            "rmse_m": m.get("rmse_m"),
            "nse": m.get("nse"),
            "bias_m": m.get("bias_m"),
        }

        if st.lat is not None and st.lon is not None:
            wis_rows.append({**base, "geometry": Point(st.lon, st.lat)})

        if r.x is not None and r.y is not None:
            section_rows.append({**base, "geometry": Point(r.x, r.y)})

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    if wis_rows:
        wis_gdf = gpd.GeoDataFrame(wis_rows, crs="EPSG:4326")
        wis_gdf.to_file(output_path, layer="wis_stations", driver="GPKG")

    if section_rows:
        sec_gdf = gpd.GeoDataFrame(section_rows, crs=section_crs)
        mode = "a" if wis_rows else "w"
        sec_gdf.to_file(output_path, layer="matched_cross_sections", driver="GPKG", mode=mode)

    return output_path
