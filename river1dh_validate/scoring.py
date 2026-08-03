"""観測所ごとの誤差指標を、一目で分かる色分けスコア表にまとめる。

「総合評価」は NSE (Nash-Sutcliffe Efficiency) を Moriasi et al. (2007) の
一般的な評価区分に当てはめたもの。NSEは平常時の水位変動が小さい観測所では
厳しく出やすい指標だが、複数観測所を横並びで比較する統一的な物差しとして
採用する (個別の当てはまりの良し悪しは各観測所のハイドログラフ図も合わせて確認する)。
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch

from .fonts import setup_japanese_font

setup_japanese_font()

# (NSEしきい値 (これより大きい場合に該当), ラベル, 色) を良い方から順に並べる。
# Moriasi et al. (2007) の評価区分を流用。
_NSE_BANDS = (
    (0.75, "Very good", "#63be7b"),
    (0.65, "Good", "#b7e1a1"),
    (0.50, "Satisfactory", "#ffeb84"),
    (float("-inf"), "Unsatisfactory", "#f4777f"),
)
_NO_DATA_LABEL = "No data"
_NO_DATA_COLOR = "#d9d9d9"

#  洪水時の水位・流量比較における基本指標セット (ユーザー確認済み):
#    水位: RMSE, Bias, ピーク(値・時刻)
#    流量: NSE, KGE, PBIAS, ピーク(値・時刻), 総量
# スコア表・全体サマリの両方で使う列定義を変量ごとに分ける。
WATERLEVEL_SCORE_COLUMNS = [
    ("station_name", "観測所"),
    ("river_name", "河川名"),
    ("kp", "KP"),
    ("match_distance_m", "マッチ距離[m]"),
    ("n_points", "点数"),
    ("rmse_m", "RMSE[m]"),
    ("bias_m", "Bias[m]"),
    ("peak_diff_m", "ピーク差[m]"),
    ("peak_time_diff_hours", "ピーク時刻差[h]"),
    ("nse", "NSE"),
    ("index_score", "総合評価"),
]

DISCHARGE_SCORE_COLUMNS = [
    ("station_name", "観測所"),
    ("river_name", "河川名"),
    ("kp", "KP"),
    ("match_distance_m", "マッチ距離[m]"),
    ("n_points", "点数"),
    ("nse", "NSE"),
    ("kge", "KGE"),
    ("pbias_percent", "PBIAS[%]"),
    ("peak_diff_m", "ピーク差[m3/s]"),
    ("peak_time_diff_hours", "ピーク時刻差[h]"),
    ("volume_diff_percent", "総量差[%]"),
    ("index_score", "総合評価"),
]

# 後方互換 (既存の呼び出し元・テストは水位用の列定義を指す)。
SCORE_COLUMNS = WATERLEVEL_SCORE_COLUMNS

# 全体サマリ行で平均を取る対象列 (変量ごとに異なる)。
WATERLEVEL_SUMMARY_MEAN_COLUMNS = (
    "match_distance_m",
    "rmse_m",
    "bias_m",
    "peak_diff_m",
    "peak_time_diff_hours",
    "nse",
)
DISCHARGE_SUMMARY_MEAN_COLUMNS = (
    "match_distance_m",
    "nse",
    "kge",
    "pbias_percent",
    "peak_diff_m",
    "peak_time_diff_hours",
    "volume_diff_percent",
)



def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and np.isnan(value))


def classify_nse(nse) -> tuple:
    """NSEから (ラベル, 色) を返す。NSEが欠損の場合は「データ無し」を返す。"""
    if _is_missing(nse):
        return _NO_DATA_LABEL, _NO_DATA_COLOR
    for threshold, label, color in _NSE_BANDS:
        if nse > threshold:
            return label, color
    return _NSE_BANDS[-1][1], _NSE_BANDS[-1][2]


def build_score_table(metrics_df: pd.DataFrame) -> pd.DataFrame:
    """`comparison_metrics.csv`相当の内容に index_score / index_color 列を追加する。"""
    df = metrics_df.copy()
    if df.empty:
        df["index_score"] = pd.Series(dtype=str)
        df["index_color"] = pd.Series(dtype=str)
        return df

    classified = df["nse"].map(classify_nse)
    df["index_score"] = [label for label, _ in classified]
    df["index_color"] = [color for _, color in classified]
    return df


def compute_overall_summary(
    score_df: pd.DataFrame, mean_columns=WATERLEVEL_SUMMARY_MEAN_COLUMNS
) -> dict:
    """全観測所を通した「全体の」指標をまとめる (スコア表の最終行に使う)。

    `mean_columns` に列挙した数値列の平均を取る。列が `score_df` に存在
    しない場合は無視する (水位/流量で異なる列セットを共通処理するため)。
    """
    with_data = score_df[score_df["n_points"] > 0] if not score_df.empty else score_df
    summary: dict = {
        "station_name": "全体 (平均)",
        "river_name": "-" if with_data.empty else f"{len(with_data)}観測所",
        "kp": np.nan,
        "n_points": 0 if with_data.empty else int(with_data["n_points"].sum()),
    }
    for col in mean_columns:
        if col == "n_points":
            continue
        summary[col] = np.nan if (with_data.empty or col not in with_data.columns) else with_data[col].mean()
    return summary


def _format_cell(col: str, value) -> str:
    if _is_missing(value):
        return "-"
    if col == "kp":
        return f"{value:.1f}"
    if col == "match_distance_m":
        return f"{value:.0f}"
    if col in ("rmse_m", "bias_m", "peak_diff_m"):
        return f"{value:+.2f}" if col == "bias_m" else f"{value:.2f}"
    if col in ("nse", "kge"):
        return f"{value:.2f}"
    if col in ("pbias_percent", "volume_diff_percent"):
        return f"{value:+.1f}"
    if col == "peak_time_diff_hours":
        return f"{value:+.1f}"
    if col == "n_points":
        return f"{int(value)}"
    return str(value)


def render_score_table_png(
    score_df: pd.DataFrame,
    output_path: Path,
    columns=WATERLEVEL_SCORE_COLUMNS,
    mean_columns=WATERLEVEL_SUMMARY_MEAN_COLUMNS,
    title: str = "観測所別 総合評価スコア表",
) -> None:
    """観測所別の総合評価を色分けした一覧表をPNGとして保存する。

    NSEの良い順に並べ、最終行に全観測所を通した「全体の」平均指標 (総合評価付き) を追加する。
    `columns`/`mean_columns` を渡すことで、水位用・流量用のどちらの列セットにも対応する。
    """
    if score_df.empty:
        return

    overall = compute_overall_summary(score_df, mean_columns)
    overall_label, overall_color = classify_nse(overall.get("nse"))

    rows = score_df.sort_values("nse", ascending=False, na_position="last").to_dict("records")

    header = [label for _, label in columns]
    cell_text = [[_format_cell(col, row.get(col)) for col, _ in columns] for row in rows]
    cell_colors = [[row["index_color"]] * len(columns) for row in rows]

    overall_row = {**overall, "index_score": overall_label}
    cell_text.append([_format_cell(col, overall_row.get(col)) for col, _ in columns])
    cell_colors.append([overall_color] * len(columns))

    n_rows = len(cell_text)
    fig_height = 1.1 + 0.4 * n_rows
    fig, ax = plt.subplots(figsize=(12, fig_height))
    ax.axis("off")
    table = ax.table(
        cellText=cell_text,
        colLabels=header,
        cellColours=cell_colors,
        colColours=["#e0e0e0"] * len(header),
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(10)
    table.scale(1, 1.7)

    # 最終行 (全体平均) を目立たせるため、枠線を太く・文字を太字にする
    n_cols = len(header)
    for col_idx in range(n_cols):
        cell = table[(n_rows, col_idx)]
        cell.set_linewidth(2.0)
        cell.set_text_props(fontweight="bold")

    ax.set_title(title, fontsize=14, pad=16)

    legend_handles = [Patch(facecolor=color, edgecolor="gray", label=label) for _, label, color in _NSE_BANDS]
    legend_handles.append(Patch(facecolor=_NO_DATA_COLOR, edgecolor="gray", label=_NO_DATA_LABEL))
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=len(legend_handles),
        frameon=False,
        fontsize=9,
        bbox_to_anchor=(0.5, 0.0),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
