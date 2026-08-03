import geopandas as gpd
import pytest
from shapely.geometry import Point

from river1dh_validate.matching import (
    AmbiguousRiverNameError,
    WisStation,
    build_river_name_to_code_map,
    match_station,
)


def make_river_points():
    """2つの河川 (RiverA: x=0..2, RiverB: x=100..102) を持つ簡単なGeoDataFrame。"""
    rows = [
        {"河川名": "RiverA", "W05_002": "A001", "KP": 0.0, "i_ID": 1, "geometry": Point(0, 0)},
        {"河川名": "RiverA", "W05_002": "A001", "KP": 1.0, "i_ID": 2, "geometry": Point(1, 0)},
        {"河川名": "RiverA", "W05_002": "A001", "KP": 2.0, "i_ID": 3, "geometry": Point(2, 0)},
        {"河川名": "RiverB", "W05_002": "B001", "KP": 0.0, "i_ID": 4, "geometry": Point(100, 0)},
        {"河川名": "RiverB", "W05_002": "B001", "KP": 1.0, "i_ID": 5, "geometry": Point(101, 0)},
    ]
    return gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:32654")


def make_station(river_name="RiverA", lat=None, lon=None):
    return WisStation(
        station_id="S1",
        station_name="テスト観測所",
        river_name=river_name,
        water_system="TestSystem",
        lat=lat,
        lon=lon,
        gauge_zero_m=10.0,
        is_active=True,
    )


def test_build_river_name_to_code_map_ok():
    river_points = make_river_points()
    name_to_code = build_river_name_to_code_map(river_points)
    assert name_to_code == {"RiverA": "A001", "RiverB": "B001"}


def test_build_river_name_to_code_map_raises_on_ambiguous_name():
    river_points = make_river_points()
    # RiverB の一部の行だけ河川コードを別物にしてしまい、曖昧な状態を作る
    river_points.loc[4, "W05_002"] = "B999"

    with pytest.raises(AmbiguousRiverNameError):
        build_river_name_to_code_map(river_points)


def test_match_station_finds_nearest_point_within_same_river_name():
    river_points = make_river_points()
    name_to_code = build_river_name_to_code_map(river_points)

    # WGS84の適当な座標(実際の投影結果は無視できるよう、投影後座標に近い点を
    # 与えるのではなく、reprojectされた点が RiverA 側に来るよう緯度経度を選ぶ)。
    # ここでは reprojection の正確性より「同じ河川名の中からのみ最近傍を選ぶ」
    # ロジックを検証したいので、CRSをWGS84のまま使う単純ケースにする。
    river_points_wgs84 = river_points.set_crs("EPSG:32654", allow_override=True).to_crs("EPSG:4326")
    station = make_station(river_name="RiverA", lat=river_points_wgs84.iloc[1].geometry.y + 0.0001, lon=river_points_wgs84.iloc[1].geometry.x)

    result = match_station(station, river_points_wgs84, name_to_code, max_distance_m=100000)

    assert result.matched
    assert result.river_code == "A001"
    assert result.i_id == 2  # RiverAの2番目の点が最も近い


def test_match_station_ignores_closer_point_from_different_river():
    """RiverBの点の方が物理的に近くても、river_nameでRiverAに絞られていれば
    RiverAの点が選ばれることを確認する (河川名フィルタが機能している証拠)。
    """
    rows = [
        {"河川名": "RiverA", "W05_002": "A001", "KP": 0.0, "i_ID": 1, "geometry": Point(0, 0)},
        # RiverBの点をターゲットのすぐ近くに置く
        {"河川名": "RiverB", "W05_002": "B001", "KP": 0.0, "i_ID": 2, "geometry": Point(0.001, 0.001)},
    ]
    river_points = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
    name_to_code = build_river_name_to_code_map(river_points)

    station = make_station(river_name="RiverA", lat=0.001, lon=0.001)
    result = match_station(station, river_points, name_to_code, max_distance_m=100000)

    assert result.matched
    assert result.river_code == "A001"
    assert result.i_id == 1


def test_match_station_unmatched_when_river_not_in_network():
    river_points = make_river_points()
    name_to_code = build_river_name_to_code_map(river_points)
    station = make_station(river_name="宍道湖", lat=35.0, lon=132.0)

    result = match_station(station, river_points, name_to_code, max_distance_m=200)

    assert not result.matched
    assert result.reason == "river_not_in_network"


def test_match_station_unmatched_when_no_coordinates():
    river_points = make_river_points()
    name_to_code = build_river_name_to_code_map(river_points)
    station = make_station(river_name="RiverA", lat=None, lon=None)

    result = match_station(station, river_points, name_to_code, max_distance_m=200)

    assert not result.matched
    assert result.reason == "no_coordinates"


def test_match_station_excluded_when_nearest_point_beyond_max_distance():
    """半径 max_distance_m 以内に断面点 (=観測所) が無い場合、たとえ河川名が
    GPKGに存在していても「未マッチ」として除外されることを確認する。"""
    # river_points は実際のGPKGと同じ投影座標系 (EPSG:6671, メートル単位) を使う。
    # 斐伊川近辺の実在しそうな座標を基準に、緯度を約0.006度(≈650m)ずらした
    # 観測所を置き、距離が閾値を超えることを確認する。
    river_point_wgs84 = gpd.GeoSeries([Point(132.9, 35.3)], crs="EPSG:4326").to_crs("EPSG:6671")
    rows = [
        {
            "河川名": "RiverA",
            "W05_002": "A001",
            "KP": 0.0,
            "i_ID": 1,
            "geometry": river_point_wgs84.iloc[0],
        }
    ]
    river_points = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:6671")
    name_to_code = build_river_name_to_code_map(river_points)

    station = make_station(river_name="RiverA", lat=35.3 + 0.006, lon=132.9)
    result = match_station(station, river_points, name_to_code, max_distance_m=200)

    assert result.distance_m > 200  # 前提: 実際に200mを超える距離であること
    assert not result.matched
    assert result.reason == "no_cross_section_within_max_distance"


def test_match_station_included_when_nearest_point_within_max_distance():
    """半径 max_distance_m 以内に断面点があれば、通常通りマッチすることを確認する。"""
    river_point_wgs84 = gpd.GeoSeries([Point(132.9, 35.3)], crs="EPSG:4326").to_crs("EPSG:6671")
    rows = [
        {
            "河川名": "RiverA",
            "W05_002": "A001",
            "KP": 0.0,
            "i_ID": 1,
            "geometry": river_point_wgs84.iloc[0],
        }
    ]
    river_points = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:6671")
    name_to_code = build_river_name_to_code_map(river_points)

    # 緯度を約0.0005度(≈55m)だけずらす -> 200m以内
    station = make_station(river_name="RiverA", lat=35.3 + 0.0005, lon=132.9)
    result = match_station(station, river_points, name_to_code, max_distance_m=200)

    assert result.distance_m < 200
    assert result.matched
    assert result.river_code == "A001"
