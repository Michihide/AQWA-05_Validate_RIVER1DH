from datetime import datetime

import pytest

from river1dh_validate.solver_io import (
    load_discharge_timeseries,
    load_waterlevel_timeseries,
    read_gpkg_path,
    series_for_i_id,
)


def test_read_gpkg_path_resolves_relative_to_csv(tmp_path):
    # 実際のAQWAリポジトリでは、"../output/Hii/gpkg_etc/river_point.gpkg" は
    # 03_Result/Hii_202107_coupled_test/ から見て 03_Result/output/... を指す
    # (1階層だけ上がる)。それに合わせた配置にする。
    gpkg_dir = tmp_path / "03_Result" / "output" / "Hii" / "gpkg_etc"
    gpkg_dir.mkdir(parents=True)
    gpkg_file = gpkg_dir / "river_point.gpkg"
    gpkg_file.write_bytes(b"")

    csv_dir = tmp_path / "03_Result" / "Hii_202107_coupled_test"
    csv_dir.mkdir(parents=True)
    csv_path = csv_dir / "timeseries_of_waterlevel_river1dh.csv"
    csv_path.write_text("../output/Hii/gpkg_etc/river_point.gpkg\nTIME,1\n0,1.0\n", encoding="utf-8")

    resolved = read_gpkg_path(csv_path)

    assert resolved == gpkg_file.resolve()


def test_read_gpkg_path_raises_when_target_missing(tmp_path):
    csv_path = tmp_path / "timeseries_of_waterlevel_river1dh.csv"
    csv_path.write_text("nonexistent/river_point.gpkg\nTIME,1\n0,1.0\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        read_gpkg_path(csv_path)


def test_load_waterlevel_timeseries_converts_epoch_to_jst_naive_datetime(tmp_path):
    csv_path = tmp_path / "timeseries_of_waterlevel_river1dh.csv"
    # 1625961600 は 2021-07-11 00:00:00 UTC。AQWAの慣例では、これがそのまま
    # 2021-07-11 00:00 JST の壁時計時刻を表すものとして扱う (utcfromtimestamp)。
    csv_path.write_text(
        "../dummy.gpkg\n"
        "TIME,10,20\n"
        "1625961600.000,1.0,2.0\n"
        "1625962200.000,1.5,2.5\n",
        encoding="utf-8",
    )

    df = load_waterlevel_timeseries(csv_path)

    assert list(df["time_jst"]) == [
        datetime(2021, 7, 11, 0, 0, 0),
        datetime(2021, 7, 11, 0, 10, 0),
    ]

    series = series_for_i_id(df, 10)
    assert series.iloc[0] == 1.0
    assert series.iloc[1] == 1.5


def test_load_discharge_timeseries_uses_same_format_as_waterlevel(tmp_path):
    csv_path = tmp_path / "timeseries_of_discharge_river1dh.csv"
    csv_path.write_text(
        "../dummy.gpkg\n"
        "TIME,10,20\n"
        "1625961600.000,100.0,200.0\n"
        "1625962200.000,150.0,250.0\n",
        encoding="utf-8",
    )

    df = load_discharge_timeseries(csv_path)

    assert list(df["time_jst"]) == [
        datetime(2021, 7, 11, 0, 0, 0),
        datetime(2021, 7, 11, 0, 10, 0),
    ]
    series = series_for_i_id(df, 10)
    assert series.iloc[0] == 100.0
    assert series.iloc[1] == 150.0


def test_series_for_i_id_raises_for_unknown_column(tmp_path):
    csv_path = tmp_path / "timeseries_of_waterlevel_river1dh.csv"
    csv_path.write_text("../dummy.gpkg\nTIME,10\n1625961600.000,1.0\n", encoding="utf-8")
    df = load_waterlevel_timeseries(csv_path)

    with pytest.raises(KeyError):
        series_for_i_id(df, 999)
