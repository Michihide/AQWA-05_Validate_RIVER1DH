from datetime import datetime
from pathlib import Path

from river1dh_validate.matching import WisStation
from river1dh_validate.wis_io import (
    load_observed_discharge_series,
    load_observed_series,
    load_stations,
)


def write_stations_csv(path: Path) -> None:
    path.write_text(
        "station_id,station_name,river_name,water_system,latitude_wgs84,longitude_wgs84,"
        "detail_gauge_zero_m,is_active\n"
        "S1,木次,斐伊川,斐伊川,35.29,132.89,36.97,TRUE\n"
        "S2,大社,日本海,斐伊川,35.40,132.66,-0.68,TRUE\n"
        "S3,北原(廃止),斐伊川,斐伊川,,,146.797,FALSE\n"
        "S4,他水系,別川,別水系,35.0,132.0,1.0,TRUE\n",
        encoding="utf-8-sig",
    )


def test_load_stations_filters_by_water_system_and_parses_optional_floats(tmp_path):
    write_stations_csv(tmp_path / "water_level_discharge_stations.csv")

    stations = load_stations(tmp_path, water_system="斐伊川")

    ids = {s.station_id for s in stations}
    assert ids == {"S1", "S2", "S3"}  # S4は別水系なので除外

    s3 = next(s for s in stations if s.station_id == "S3")
    assert s3.lat is None
    assert s3.lon is None
    assert s3.gauge_zero_m == 146.797
    assert s3.is_active is False

    s1 = next(s for s in stations if s.station_id == "S1")
    assert s1.lat == 35.29
    assert s1.gauge_zero_m == 36.97
    assert s1.is_active is True


def make_station(gauge_zero_m=36.97):
    return WisStation(
        station_id="S1",
        station_name="木次",
        river_name="斐伊川",
        water_system="斐伊川",
        lat=35.29,
        lon=132.89,
        gauge_zero_m=gauge_zero_m,
        is_active=True,
    )


def test_load_observed_series_applies_datum_conversion_and_drops_missing(tmp_path):
    ts_dir = tmp_path / "timeseries"
    ts_dir.mkdir()
    (ts_dir / "S1.csv").write_text(
        "station_id,datetime,water_level_m,flag,is_provisional,retrieved_at\n"
        "S1,2021-07-11 00:00,1.75,,FALSE,2026-01-01T00:00:00+09:00\n"
        "S1,2021-07-11 01:00,,$,FALSE,2026-01-01T00:00:00+09:00\n"  # 欠測 -> 除外されるべき
        "S1,2021-07-11 02:00,1.80,,FALSE,2026-01-01T00:00:00+09:00\n"
        "S1,2021-07-13 00:00,2.00,,FALSE,2026-01-01T00:00:00+09:00\n",  # 期間外 -> 除外されるべき
        encoding="utf-8",
    )

    station = make_station()
    series = load_observed_series(
        tmp_path, station, datetime(2021, 7, 11, 0, 0), datetime(2021, 7, 12, 0, 0)
    )

    assert len(series) == 2
    assert series.iloc[0] == 1.75 + 36.97
    assert series.iloc[1] == 1.80 + 36.97


def test_load_observed_series_returns_empty_when_gauge_zero_unknown(tmp_path):
    ts_dir = tmp_path / "timeseries"
    ts_dir.mkdir()
    (ts_dir / "S1.csv").write_text(
        "station_id,datetime,water_level_m,flag,is_provisional,retrieved_at\n"
        "S1,2021-07-11 00:00,1.75,,FALSE,2026-01-01T00:00:00+09:00\n",
        encoding="utf-8",
    )

    station = make_station(gauge_zero_m=None)
    series = load_observed_series(
        tmp_path, station, datetime(2021, 7, 11), datetime(2021, 7, 12)
    )

    assert series.empty


def test_load_observed_series_returns_empty_when_file_missing(tmp_path):
    station = make_station()
    series = load_observed_series(
        tmp_path, station, datetime(2021, 7, 11), datetime(2021, 7, 12)
    )

    assert series.empty


def test_load_observed_discharge_series_drops_missing_and_out_of_range(tmp_path):
    ts_dir = tmp_path / "timeseries_discharge"
    ts_dir.mkdir()
    (ts_dir / "S1.csv").write_text(
        "station_id,datetime,discharge_m3s,flag,is_provisional,retrieved_at\n"
        "S1,2021-07-11 00:00,47.41,,FALSE,2026-01-01T00:00:00+09:00\n"
        "S1,2021-07-11 01:00,,$,FALSE,2026-01-01T00:00:00+09:00\n"  # 欠測 -> 除外
        "S1,2021-07-11 02:00,50.00,,FALSE,2026-01-01T00:00:00+09:00\n"
        "S1,2021-07-13 00:00,60.00,,FALSE,2026-01-01T00:00:00+09:00\n",  # 期間外 -> 除外
        encoding="utf-8",
    )

    station = make_station()
    series = load_observed_discharge_series(
        tmp_path, station, datetime(2021, 7, 11, 0, 0), datetime(2021, 7, 12, 0, 0)
    )

    # 水位と違い、零点高の加算は行わない (生の m3/s 値のまま)。
    assert len(series) == 2
    assert series.iloc[0] == 47.41
    assert series.iloc[1] == 50.00


def test_load_observed_discharge_series_returns_empty_when_file_missing(tmp_path):
    station = make_station()
    series = load_observed_discharge_series(
        tmp_path, station, datetime(2021, 7, 11), datetime(2021, 7, 12)
    )

    assert series.empty
