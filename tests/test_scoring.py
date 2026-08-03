import math

import pandas as pd

from river1dh_validate.scoring import (
    DISCHARGE_SCORE_COLUMNS,
    DISCHARGE_SUMMARY_MEAN_COLUMNS,
    build_score_table,
    classify_nse,
    compute_overall_summary,
    render_score_table_png,
)


def test_classify_nse_bands():
    assert classify_nse(0.9)[0] == "Very good"
    assert classify_nse(0.75)[0] == "Good"  # 境界値ちょうどは「より大きい」でないため上位に入らない
    assert classify_nse(0.76)[0] == "Very good"
    assert classify_nse(0.70)[0] == "Good"
    assert classify_nse(0.60)[0] == "Satisfactory"
    assert classify_nse(0.10)[0] == "Unsatisfactory"
    assert classify_nse(-5.0)[0] == "Unsatisfactory"


def test_classify_nse_missing_value_returns_no_data():
    assert classify_nse(None)[0] == "No data"
    assert classify_nse(float("nan"))[0] == "No data"


def test_classify_nse_labels_have_distinct_colors():
    labels_colors = {classify_nse(v) for v in (0.9, 0.7, 0.55, 0.1, None)}
    labels = {label for label, _ in labels_colors}
    colors = {color for _, color in labels_colors}
    assert len(labels) == 5
    assert len(colors) == 5  # 色もすべて異なる (視覚的に区別できる)


def make_metrics_df():
    return pd.DataFrame(
        [
            {
                "station_id": "S1",
                "station_name": "駅A",
                "river_name": "RiverA",
                "kp": 10.0,
                "match_distance_m": 50.0,
                "n_points": 49,
                "rmse_m": 0.5,
                "nse": 0.9,
                "peak_diff_m": -0.3,
                "peak_time_diff_hours": 0.0,
            },
            {
                "station_id": "S2",
                "station_name": "駅B",
                "river_name": "RiverA",
                "kp": 5.0,
                "match_distance_m": 150.0,
                "n_points": 49,
                "rmse_m": 5.0,
                "nse": -2.0,
                "peak_diff_m": 3.0,
                "peak_time_diff_hours": -2.0,
            },
        ]
    )


def test_build_score_table_adds_index_columns():
    df = make_metrics_df()
    score_df = build_score_table(df)

    assert "index_score" in score_df.columns
    assert "index_color" in score_df.columns
    assert score_df.loc[score_df["station_id"] == "S1", "index_score"].iloc[0] == "Very good"
    assert score_df.loc[score_df["station_id"] == "S2", "index_score"].iloc[0] == "Unsatisfactory"


def test_build_score_table_handles_empty_dataframe():
    empty = pd.DataFrame(
        columns=[
            "station_id",
            "station_name",
            "river_name",
            "kp",
            "match_distance_m",
            "n_points",
            "rmse_m",
            "nse",
            "peak_diff_m",
            "peak_time_diff_hours",
        ]
    )
    score_df = build_score_table(empty)
    assert score_df.empty
    assert "index_score" in score_df.columns


def test_compute_overall_summary_averages_only_stations_with_data():
    df = make_metrics_df()
    score_df = build_score_table(df)
    # n_points=0 の行 (データ無し) を1つ追加して、平均計算から除外されることを確認する
    no_data_row = {
        "station_id": "S3",
        "station_name": "駅C",
        "river_name": "RiverA",
        "kp": 1.0,
        "match_distance_m": 10.0,
        "n_points": 0,
        "rmse_m": float("nan"),
        "nse": float("nan"),
        "peak_diff_m": float("nan"),
        "peak_time_diff_hours": float("nan"),
        "index_score": "No data",
        "index_color": "#d9d9d9",
    }
    score_df = pd.concat([score_df, pd.DataFrame([no_data_row])], ignore_index=True)

    overall = compute_overall_summary(score_df)

    assert overall["nse"] == (0.9 + -2.0) / 2
    assert overall["rmse_m"] == (0.5 + 5.0) / 2
    assert "2" in overall["river_name"]  # "2観測所" のような文言に、データありの2件だけが反映される


def test_render_score_table_png_creates_file(tmp_path):
    df = make_metrics_df()
    score_df = build_score_table(df)
    output_path = tmp_path / "score_table.png"

    render_score_table_png(score_df, output_path)

    assert output_path.exists()
    assert output_path.stat().st_size > 0


def test_render_score_table_png_noop_on_empty_dataframe(tmp_path):
    empty_score_df = build_score_table(pd.DataFrame())
    output_path = tmp_path / "score_table.png"

    render_score_table_png(empty_score_df, output_path)

    assert not output_path.exists()


def make_discharge_metrics_df():
    return pd.DataFrame(
        [
            {
                "station_id": "S1",
                "station_name": "駅A",
                "river_name": "RiverA",
                "kp": 10.0,
                "match_distance_m": 50.0,
                "n_points": 49,
                "nse": 0.9,
                "kge": 0.85,
                "pbias_percent": 5.0,
                "peak_diff_m": -3.0,
                "peak_time_diff_hours": 0.0,
                "volume_diff_percent": -2.0,
            },
            {
                "station_id": "S2",
                "station_name": "駅B",
                "river_name": "RiverA",
                "kp": 5.0,
                "match_distance_m": 150.0,
                "n_points": 49,
                "nse": -2.0,
                "kge": -1.0,
                "pbias_percent": -30.0,
                "peak_diff_m": 30.0,
                "peak_time_diff_hours": -2.0,
                "volume_diff_percent": 25.0,
            },
        ]
    )


def test_compute_overall_summary_supports_discharge_mean_columns():
    df = make_discharge_metrics_df()
    score_df = build_score_table(df)

    overall = compute_overall_summary(score_df, DISCHARGE_SUMMARY_MEAN_COLUMNS)

    assert overall["nse"] == (0.9 + -2.0) / 2
    assert overall["kge"] == (0.85 + -1.0) / 2
    assert overall["pbias_percent"] == (5.0 + -30.0) / 2
    assert overall["volume_diff_percent"] == (-2.0 + 25.0) / 2
    # 水位専用列は要求していないので入らない
    assert "rmse_m" not in overall


def test_render_score_table_png_supports_discharge_columns(tmp_path):
    df = make_discharge_metrics_df()
    score_df = build_score_table(df)
    output_path = tmp_path / "discharge_score_table.png"

    render_score_table_png(
        score_df,
        output_path,
        columns=DISCHARGE_SCORE_COLUMNS,
        mean_columns=DISCHARGE_SUMMARY_MEAN_COLUMNS,
        title="観測所別 流量総合評価スコア表",
    )

    assert output_path.exists()
    assert output_path.stat().st_size > 0
