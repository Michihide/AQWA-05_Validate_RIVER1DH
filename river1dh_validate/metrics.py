"""観測値とソルバー結果の時系列を突き合わせて誤差指標を計算する。

ソルバー出力は10分間隔、WIS観測値は観測所や年代によって間隔がまちまち
(古いデータは1時間間隔のことが多い) なので、ソルバー側の連続な時系列を
線形補間して観測タイムスタンプ上に載せる (逆に観測側を補間すると、
観測の欠測が実際より滑らかに見えてしまうため)。

洪水時の水位・流量比較における基本指標セット (ユーザー確認済み):
  - 水位: RMSE, Bias, ピーク(値・時刻)
  - 流量: NSE, KGE, PBIAS, ピーク(値・時刻), 総量

このモジュールでは両方の変量で使えるよう指標を一括計算し、どれを主に
表示するかは呼び出し側 (compare_stations.py / scoring.py) が変量ごとに選ぶ。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd


@dataclass
class ComparisonMetrics:
    n_points: int
    rmse_m: Optional[float]
    mae_m: Optional[float]
    bias_m: Optional[float]
    nse: Optional[float]
    kge: Optional[float]
    pbias_percent: Optional[float]
    obs_peak_m: Optional[float]
    obs_peak_time: Optional[pd.Timestamp]
    sim_peak_m: Optional[float]
    sim_peak_time: Optional[pd.Timestamp]
    peak_diff_m: Optional[float]
    peak_time_diff_hours: Optional[float]
    obs_volume_m3: Optional[float]
    sim_volume_m3: Optional[float]
    volume_diff_percent: Optional[float]


def align_series(sim_series: pd.Series, obs_series: pd.Series) -> pd.DataFrame:
    """`sim_series` を `obs_series` のタイムスタンプ上に線形補間して揃える。

    ソルバーの期間外に出る観測タイムスタンプは (`limit_area='inside'` により)
    補間せず NaN のままにし、後段の指標計算で自然に除外されるようにする。
    """
    if obs_series.empty or sim_series.empty:
        return pd.DataFrame(columns=["obs", "sim"])

    combined_index = sim_series.index.union(obs_series.index)
    sim_on_combined = sim_series.reindex(combined_index).interpolate(
        method="time", limit_area="inside"
    )
    sim_on_obs = sim_on_combined.reindex(obs_series.index)

    aligned = pd.DataFrame({"obs": obs_series, "sim": sim_on_obs}).dropna()
    return aligned


def _empty_metrics() -> ComparisonMetrics:
    return ComparisonMetrics(
        n_points=0,
        rmse_m=None,
        mae_m=None,
        bias_m=None,
        nse=None,
        kge=None,
        pbias_percent=None,
        obs_peak_m=None,
        obs_peak_time=None,
        sim_peak_m=None,
        sim_peak_time=None,
        peak_diff_m=None,
        peak_time_diff_hours=None,
        obs_volume_m3=None,
        sim_volume_m3=None,
        volume_diff_percent=None,
    )


def _compute_kge(obs: pd.Series, sim: pd.Series) -> Optional[float]:
    """Kling-Gupta Efficiency (Gupta et al., 2009)。

    KGE = 1 - sqrt((r-1)^2 + (alpha-1)^2 + (beta-1)^2)
      r     : obs と sim の相関係数
      alpha : sim.std() / obs.std() (変動の再現性)
      beta  : sim.mean() / obs.mean() (バイアスの比)

    obs の標準偏差や平均が 0 (=一定値) の場合は定義できないため None を返す。
    """
    if len(obs) < 2:
        return None
    obs_std = obs.std()
    obs_mean = obs.mean()
    if obs_std == 0 or obs_mean == 0:
        return None
    r = obs.corr(sim)
    if r is None or (isinstance(r, float) and np.isnan(r)):
        return None
    alpha = sim.std() / obs_std
    beta = sim.mean() / obs_mean
    return float(1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2))


def _compute_pbias_percent(obs: pd.Series, sim: pd.Series) -> Optional[float]:
    """PBIAS (%) = 100 * sum(obs - sim) / sum(obs) (Moriasi et al., 2007 の定義)。

    正: モデルが過小評価 (under-prediction)、負: 過大評価 (over-prediction)。
    """
    obs_sum = obs.sum()
    if obs_sum == 0:
        return None
    return float(100.0 * (obs_sum - sim.sum()) / obs_sum)


def _compute_volume_m3(series: pd.Series) -> Optional[float]:
    """時系列を台形積分し、区間内の総量 [m3] を返す (流量 [m3/s] 前提)。

    2点未満では積分できないため None を返す。
    """
    if len(series) < 2:
        return None
    seconds = (series.index - series.index[0]).total_seconds().to_numpy()
    if hasattr(np, "trapezoid"):
        trapz_fn = np.trapezoid
    else:
        trapz_fn = np.trapz
    return float(trapz_fn(series.to_numpy(), x=seconds))


def compute_metrics(aligned: pd.DataFrame) -> ComparisonMetrics:
    if aligned.empty:
        return _empty_metrics()

    obs = aligned["obs"]
    sim = aligned["sim"]
    error = sim - obs

    rmse = float(np.sqrt((error**2).mean()))
    mae = float(error.abs().mean())
    bias = float(error.mean())

    obs_mean = obs.mean()
    denom = ((obs - obs_mean) ** 2).sum()
    nse = float(1 - (error**2).sum() / denom) if denom > 0 else None

    kge = _compute_kge(obs, sim)
    pbias_percent = _compute_pbias_percent(obs, sim)

    obs_peak_time = obs.idxmax()
    obs_peak_m = float(obs.loc[obs_peak_time])
    sim_peak_time = sim.idxmax()
    sim_peak_m = float(sim.loc[sim_peak_time])

    peak_diff_m = sim_peak_m - obs_peak_m
    peak_time_diff_hours = (sim_peak_time - obs_peak_time).total_seconds() / 3600.0

    obs_volume_m3 = _compute_volume_m3(obs)
    sim_volume_m3 = _compute_volume_m3(sim)
    volume_diff_percent = (
        float(100.0 * (sim_volume_m3 - obs_volume_m3) / obs_volume_m3)
        if obs_volume_m3 is not None and sim_volume_m3 is not None and obs_volume_m3 != 0
        else None
    )

    return ComparisonMetrics(
        n_points=len(aligned),
        rmse_m=rmse,
        mae_m=mae,
        bias_m=bias,
        nse=nse,
        kge=kge,
        pbias_percent=pbias_percent,
        obs_peak_m=obs_peak_m,
        obs_peak_time=obs_peak_time,
        sim_peak_m=sim_peak_m,
        sim_peak_time=sim_peak_time,
        peak_diff_m=peak_diff_m,
        peak_time_diff_hours=peak_time_diff_hours,
        obs_volume_m3=obs_volume_m3,
        sim_volume_m3=sim_volume_m3,
        volume_diff_percent=volume_diff_percent,
    )
