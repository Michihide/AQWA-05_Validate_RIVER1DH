import pandas as pd
import pytest

from river1dh_validate.metrics import align_series, compute_metrics


def make_time_index(start, periods, freq):
    return pd.date_range(start, periods=periods, freq=freq)


def test_compute_metrics_perfect_match_gives_zero_error_and_nse_one():
    idx = make_time_index("2021-07-11", 5, "h")
    values = [10.0, 11.0, 12.0, 11.0, 10.0]
    aligned = pd.DataFrame({"obs": values, "sim": values}, index=idx)

    m = compute_metrics(aligned)

    assert m.n_points == 5
    assert m.rmse_m == 0.0
    assert m.mae_m == 0.0
    assert m.bias_m == 0.0
    assert m.nse == 1.0
    assert m.obs_peak_m == 12.0
    assert m.sim_peak_m == 12.0
    assert m.peak_diff_m == 0.0
    assert m.peak_time_diff_hours == 0.0


def test_compute_metrics_detects_peak_timing_and_value_offset():
    idx = make_time_index("2021-07-11", 4, "h")
    obs = pd.Series([1.0, 3.0, 1.0, 0.5], index=idx)  # peaks at hour 1
    sim = pd.Series([1.0, 1.5, 3.5, 1.0], index=idx)  # peaks at hour 2 (1h late), value +0.5

    aligned = pd.DataFrame({"obs": obs, "sim": sim})
    m = compute_metrics(aligned)

    assert m.obs_peak_time == idx[1]
    assert m.sim_peak_time == idx[2]
    assert m.peak_time_diff_hours == 1.0
    assert m.peak_diff_m == 0.5


def test_compute_metrics_empty_returns_none_fields():
    m = compute_metrics(pd.DataFrame(columns=["obs", "sim"]))

    assert m.n_points == 0
    assert m.rmse_m is None
    assert m.nse is None
    assert m.obs_peak_time is None
    assert m.kge is None
    assert m.pbias_percent is None
    assert m.obs_volume_m3 is None
    assert m.sim_volume_m3 is None
    assert m.volume_diff_percent is None


def test_compute_metrics_perfect_match_gives_kge_one_and_pbias_zero():
    idx = make_time_index("2021-07-11", 5, "h")
    values = [10.0, 11.0, 12.0, 11.0, 10.0]
    aligned = pd.DataFrame({"obs": values, "sim": values}, index=idx)

    m = compute_metrics(aligned)

    assert m.kge == 1.0
    assert m.pbias_percent == 0.0
    assert m.volume_diff_percent == 0.0


def test_compute_metrics_pbias_positive_when_model_underestimates():
    idx = make_time_index("2021-07-11", 4, "h")
    obs = pd.Series([10.0, 20.0, 30.0, 20.0], index=idx)
    sim = obs * 0.9  # モデルが常に1割過小評価

    aligned = pd.DataFrame({"obs": obs, "sim": sim})
    m = compute_metrics(aligned)

    assert m.pbias_percent is not None
    assert m.pbias_percent == pytest.approx(10.0)


def test_compute_metrics_pbias_negative_when_model_overestimates():
    idx = make_time_index("2021-07-11", 4, "h")
    obs = pd.Series([10.0, 20.0, 30.0, 20.0], index=idx)
    sim = obs * 1.1  # モデルが常に1割過大評価

    aligned = pd.DataFrame({"obs": obs, "sim": sim})
    m = compute_metrics(aligned)

    assert m.pbias_percent == pytest.approx(-10.0)


def test_compute_metrics_kge_is_none_when_obs_is_constant():
    idx = make_time_index("2021-07-11", 4, "h")
    obs = pd.Series([5.0, 5.0, 5.0, 5.0], index=idx)
    sim = pd.Series([5.0, 6.0, 4.0, 5.0], index=idx)

    aligned = pd.DataFrame({"obs": obs, "sim": sim})
    m = compute_metrics(aligned)

    assert m.kge is None


def test_compute_metrics_total_volume_matches_trapezoidal_integration():
    # 一定流量 10 m3/s が 3600秒 (1時間) 続けば、積分値は 10*3600 = 36000 m3 に近いはず。
    idx = pd.date_range("2021-07-11 00:00", periods=2, freq="h")
    obs = pd.Series([10.0, 10.0], index=idx)
    sim = pd.Series([20.0, 20.0], index=idx)

    aligned = pd.DataFrame({"obs": obs, "sim": sim})
    m = compute_metrics(aligned)

    assert m.obs_volume_m3 == pytest.approx(36000.0)
    assert m.sim_volume_m3 == pytest.approx(72000.0)
    assert m.volume_diff_percent == pytest.approx(100.0)


def test_align_series_interpolates_finer_sim_onto_sparser_obs_timestamps():
    # simは10分間隔、obsは1時間間隔という現実のシナリオを模す
    sim_idx = pd.date_range("2021-07-11 00:00", periods=7, freq="10min")
    sim = pd.Series([0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0], index=sim_idx)

    obs_idx = pd.to_datetime(["2021-07-11 00:00", "2021-07-11 01:00"])
    obs = pd.Series([0.0, 6.0], index=obs_idx)

    aligned = align_series(sim, obs)

    assert list(aligned.index) == list(obs_idx)
    assert aligned.loc[obs_idx[0], "sim"] == 0.0
    assert aligned.loc[obs_idx[1], "sim"] == 6.0


def test_align_series_drops_obs_timestamps_outside_sim_range():
    sim_idx = pd.date_range("2021-07-11 00:00", periods=3, freq="h")
    sim = pd.Series([1.0, 2.0, 3.0], index=sim_idx)

    obs_idx = pd.to_datetime(["2021-07-10 23:00", "2021-07-11 01:00", "2021-07-12 00:00"])
    obs = pd.Series([10.0, 20.0, 30.0], index=obs_idx)

    aligned = align_series(sim, obs)

    # sim範囲内 (2021-07-11 01:00) のみが残る
    assert len(aligned) == 1
    assert aligned.index[0] == pd.Timestamp("2021-07-11 01:00")


def test_align_series_empty_inputs_return_empty_dataframe():
    empty = pd.Series(dtype=float)
    non_empty = pd.Series([1.0], index=pd.to_datetime(["2021-07-11"]))

    assert align_series(empty, non_empty).empty
    assert align_series(non_empty, empty).empty
