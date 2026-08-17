"""観測値とソルバー結果を重ね描きするハイドログラフ図。"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # ヘッドレス環境でも動くように、画面表示は行わない
import matplotlib.pyplot as plt
import pandas as pd

from .fonts import setup_japanese_font
from .matching import MatchResult
from .metrics import ComparisonMetrics

setup_japanese_font()


def plot_comparison(
    match: MatchResult,
    obs_series: pd.Series,
    sim_series: pd.Series,
    metrics: ComparisonMetrics,
    output_path: Path,
    variable: str = "waterlevel",
) -> None:
    """観測値 vs シミュレーションのハイドログラフを描く。

    `variable` は "waterlevel" (水位、既定) または "discharge" (流量)。
    軸ラベル・凡例統計の内訳を、ユーザー確認済みの基本指標セットに合わせて
    切り替える (水位: RMSE/Bias/ピーク/時刻、流量: NSE/KGE/PBIAS/ピーク/時刻/総量)。
    """
    station = match.station
    fig, ax = plt.subplots(figsize=(10, 5))

    if variable == "discharge":
        ylabel = "Discharge [m3/s]"
        sim_label = "Simulated discharge (RIVER1DH)"
        obs_label = "Observed discharge (WIS)"
        peak_unit = "m3/s"
    else:
        ylabel = "Water level [m, T.P.]"
        sim_label = "Simulated (RIVER1DH)"
        obs_label = "Observed (WIS)"
        peak_unit = "m"

    if not sim_series.empty:
        ax.plot(sim_series.index, sim_series.values, label=sim_label, color="tab:orange")
    if not obs_series.empty:
        ax.plot(
            obs_series.index,
            obs_series.values,
            label=obs_label,
            color="tab:blue",
            marker="o",
            markersize=2,
            linewidth=1,
        )

    if variable == "waterlevel":
        level_styles = (
            ("水防団待機", "gold", ":"),
            ("氾濫注意", "darkorange", "--"),
            ("避難判断", "crimson", "--"),
            ("氾濫危険", "darkred", "-."),
            ("計画高水位", "purple", "-."),
        )
        style_by_label = {label: (color, ls) for label, color, ls in level_styles}
        for label, wl_tp in station.reference_water_levels_tp():
            color, ls = style_by_label.get(label, ("gray", "--"))
            ax.axhline(
                wl_tp,
                color=color,
                linestyle=ls,
                linewidth=1.2,
                alpha=0.85,
                label=f"{label} ({wl_tp:.2f} m)",
            )

    kp_label = f"KP={match.kp:.1f}" if match.kp is not None else "KP=?"
    title = f"{station.station_name} ({station.station_id}) — {station.river_name} {kp_label}"
    ax.set_xlabel("Time (JST)")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend(loc="upper left")
    ax.grid(True, alpha=0.3)
    fig.autofmt_xdate()

    if metrics.n_points > 0:
        if variable == "discharge":
            lines = []
            if metrics.nse is not None:
                lines.append(f"NSE={metrics.nse:.2f}")
            if metrics.kge is not None:
                lines.append(f"KGE={metrics.kge:.2f}")
            if metrics.pbias_percent is not None:
                lines.append(f"PBIAS={metrics.pbias_percent:+.1f}%")
            lines.append(f"Peak diff={metrics.peak_diff_m:+.2f} {peak_unit}")
            lines.append(f"Peak time diff={metrics.peak_time_diff_hours:+.1f} h")
            if metrics.volume_diff_percent is not None:
                lines.append(f"Volume diff={metrics.volume_diff_percent:+.1f}%")
        else:
            lines = [f"RMSE={metrics.rmse_m:.2f} m", f"Bias={metrics.bias_m:+.2f} m"]
            if metrics.nse is not None:
                lines.append(f"NSE={metrics.nse:.2f}")
            lines.append(f"Peak diff={metrics.peak_diff_m:+.2f} {peak_unit}")
            lines.append(f"Peak time diff={metrics.peak_time_diff_hours:+.1f} h")
        lines.append(f"Match dist={match.distance_m:.0f} m")
        text = "\n".join(lines)
        ax.text(
            0.99,
            0.02,
            text,
            transform=ax.transAxes,
            ha="right",
            va="bottom",
            fontsize=9,
            bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)
