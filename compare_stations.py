#!/usr/bin/env python3
"""WIS観測所とRIVER1DHソルバー結果 (水位) を比較するツール。

使い方:
    python compare_stations.py --config config/hii_202107.yaml

出力 (config の output_dir 以下):
    comparison_metrics.csv  - マッチした観測所ごとの水位誤差指標 (RMSE/Bias/ピーク/時刻/NSE)
    unmatched_stations.csv  - マッチしなかった観測所とその理由
    station_scores.csv      - comparison_metrics.csv + 総合評価 (index_score) 列
    score_table.png         - 観測所別の水位総合評価を色分けした一覧表 (全体の平均行つき)
    plots/<station_id>_<station_name>.png - 水位: 観測値 vs シミュレーション のグラフ

    (config.discharge_csv が設定されている場合、流量についても同様に出力)
    discharge_comparison_metrics.csv - マッチした観測所ごとの流量誤差指標 (NSE/KGE/PBIAS/ピーク/総量)
    discharge_station_scores.csv     - 上記 + 総合評価 (index_score) 列
    discharge_score_table.png        - 観測所別の流量総合評価を色分けした一覧表
    plots_discharge/<station_id>_<station_name>.png - 流量: 観測値 vs シミュレーション のグラフ

1つの河川名が複数の河川コードに対応しているなど、データ構造上あっては
ならない状態を検出した場合はエラーで停止する (静かにフォールバックしない)。
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

from river1dh_validate import metrics as metrics_mod
from river1dh_validate import scoring, solver_io, wis_io
from river1dh_validate.config import load_config
from river1dh_validate.matching import match_all, results_to_frames
from river1dh_validate.plotting import plot_comparison

logger = logging.getLogger(__name__)


def _sanitize_filename(text: str) -> str:
    return re.sub(r"[\\/:*?\"<>|]", "_", text)


def _compute_variable_metrics(
    matched_results: list,
    sim_df: pd.DataFrame,
    sim_start,
    sim_end,
    obs_loader,
    plots_dir: Path,
    variable: str,
) -> pd.DataFrame:
    """マッチした観測所ごとに、指定した変量 (water level / discharge) の
    観測値 vs シミュレーションを突き合わせ、指標一覧のDataFrameを返す。

    `ComparisonMetrics` は水位・流量どちらの変量でも同じ指標一式
    (RMSE/Bias/NSE/KGE/PBIAS/ピーク/総量) を計算するため、行の構造は共通。
    どの列を主に見るかは呼び出し側 (scoring の列定義) が変量ごとに選ぶ。
    """
    rows = []
    for match in matched_results:
        station = match.station
        sim_series = solver_io.series_for_i_id(sim_df, match.i_id)
        obs_series = obs_loader(station, sim_start, sim_end)
        aligned = metrics_mod.align_series(sim_series, obs_series)
        m = metrics_mod.compute_metrics(aligned)

        if m.n_points == 0:
            logger.warning(
                "station_id=%s (%s) [%s]: 観測期間と重なるデータがありません (観測値未取得の可能性)",
                station.station_id,
                station.station_name,
                variable,
            )

        rows.append(
            {
                "station_id": station.station_id,
                "station_name": station.station_name,
                "river_name": station.river_name,
                "river_code": match.river_code,
                "kp": match.kp,
                "i_id": match.i_id,
                "match_distance_m": match.distance_m,
                "n_points": m.n_points,
                "rmse_m": m.rmse_m,
                "mae_m": m.mae_m,
                "bias_m": m.bias_m,
                "nse": m.nse,
                "kge": m.kge,
                "pbias_percent": m.pbias_percent,
                "obs_peak_m": m.obs_peak_m,
                "obs_peak_time": m.obs_peak_time,
                "sim_peak_m": m.sim_peak_m,
                "sim_peak_time": m.sim_peak_time,
                "peak_diff_m": m.peak_diff_m,
                "peak_time_diff_hours": m.peak_time_diff_hours,
                "obs_volume_m3": m.obs_volume_m3,
                "sim_volume_m3": m.sim_volume_m3,
                "volume_diff_percent": m.volume_diff_percent,
            }
        )

        filename = _sanitize_filename(f"{station.station_id}_{station.station_name}.png")
        plot_comparison(match, obs_series, sim_series, m, plots_dir / filename, variable=variable)

    return pd.DataFrame(rows)


def run(config_path: str) -> int:
    config = load_config(config_path)
    logger.info("event=%s result_dir=%s", config.event_name, config.result_dir)

    waterlevel_csv_path = config.waterlevel_csv_path
    if not waterlevel_csv_path.exists():
        logger.error("ソルバー出力CSVが見つかりません: %s", waterlevel_csv_path)
        return 1

    river_points = solver_io.load_river_points(waterlevel_csv_path)
    sim_df = solver_io.load_waterlevel_timeseries(waterlevel_csv_path)
    sim_start = sim_df["time_jst"].min()
    sim_end = sim_df["time_jst"].max()
    logger.info(
        "ソルバー出力: %s 行, 期間 %s 〜 %s (%d断面点)",
        len(sim_df),
        sim_start,
        sim_end,
        len(river_points),
    )

    stations = wis_io.load_stations(config.wis_output_dir, config.water_system)
    logger.info("対象水系 (%s) の観測所数: %d", config.water_system, len(stations))
    if not stations:
        logger.error(
            "water_system=%s の観測所が見つかりません。wis_output_dir の設定を確認してください: %s",
            config.water_system,
            config.wis_output_dir,
        )
        return 1

    # マッチング。河川名が複数の河川コードに対応している場合はここで例外が飛ぶ
    # (AmbiguousRiverNameError) — 構造上あってはならない状態なので、意図的に
    # フォールバックせず処理全体を停止する。
    # なお、最も近い断面点までの距離が max_distance_m を超える観測所 (=半径
    # max_distance_m 以内に断面点/観測所が無いケース) はここでハードに除外され、
    # unmatched_df 側に回る。
    results = match_all(stations, river_points, config.match.max_distance_m)
    matched_df, unmatched_df = results_to_frames(results)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    plots_dir = config.output_dir / "plots"

    matched_results = [r for r in results if r.matched]
    metrics_df = _compute_variable_metrics(
        matched_results,
        sim_df,
        sim_start,
        sim_end,
        lambda station, start, end: wis_io.load_observed_series(
            config.wis_output_dir, station, start, end
        ),
        plots_dir,
        variable="waterlevel",
    )
    metrics_csv_path = config.output_dir / "comparison_metrics.csv"
    metrics_df.to_csv(metrics_csv_path, index=False, encoding="utf-8-sig")

    unmatched_csv_path = config.output_dir / "unmatched_stations.csv"
    unmatched_df.to_csv(unmatched_csv_path, index=False, encoding="utf-8-sig")

    score_df = scoring.build_score_table(metrics_df)
    scores_csv_path = config.output_dir / "station_scores.csv"
    score_df.to_csv(scores_csv_path, index=False, encoding="utf-8-sig")
    score_table_png_path = config.output_dir / "score_table.png"
    scoring.render_score_table_png(
        score_df,
        score_table_png_path,
        columns=scoring.WATERLEVEL_SCORE_COLUMNS,
        title="観測所別 水位 総合評価スコア表",
    )

    logger.info("マッチ数: %d / %d, 未マッチ: %d", len(matched_df), len(stations), len(unmatched_df))
    print(f"matched={len(matched_df)} unmatched={len(unmatched_df)} total={len(stations)}")
    if not metrics_df.empty:
        with_data = metrics_df[metrics_df["n_points"] > 0]
        if not with_data.empty:
            print(f"avg RMSE={with_data['rmse_m'].mean():.3f} m over {len(with_data)} stations with data")
            overall = scoring.compute_overall_summary(score_df)
            overall_label, _ = scoring.classify_nse(overall["nse"])
            print(f"overall NSE={overall['nse']:.3f} ({overall_label})")
    print(f"metrics -> {metrics_csv_path}")
    print(f"unmatched -> {unmatched_csv_path}")
    print(f"scores -> {scores_csv_path}")
    print(f"score table -> {score_table_png_path}")
    print(f"plots -> {plots_dir}")

    # --- 流量比較 (discharge_csv が設定されている場合のみ) -----------------
    # マッチング (観測所 <-> 断面点 i_ID) は変量によらず共通のため、水位で
    # 計算した matched_results (= results から matched=True のみ抽出したもの)
    # をそのまま再利用する。
    discharge_csv_path = config.discharge_csv_path
    if discharge_csv_path is None:
        logger.info("discharge_csv が未設定のため、流量比較はスキップします。")
    elif not discharge_csv_path.exists():
        logger.warning("流量ソルバー出力CSVが見つからないため、流量比較はスキップします: %s", discharge_csv_path)
    else:
        discharge_sim_df = solver_io.load_discharge_timeseries(discharge_csv_path)
        discharge_sim_start = discharge_sim_df["time_jst"].min()
        discharge_sim_end = discharge_sim_df["time_jst"].max()
        logger.info(
            "流量ソルバー出力: %s 行, 期間 %s 〜 %s",
            len(discharge_sim_df),
            discharge_sim_start,
            discharge_sim_end,
        )

        discharge_plots_dir = config.output_dir / "plots_discharge"
        discharge_metrics_df = _compute_variable_metrics(
            matched_results,
            discharge_sim_df,
            discharge_sim_start,
            discharge_sim_end,
            lambda station, start, end: wis_io.load_observed_discharge_series(
                config.wis_output_dir, station, start, end
            ),
            discharge_plots_dir,
            variable="discharge",
        )
        discharge_metrics_csv_path = config.output_dir / "discharge_comparison_metrics.csv"
        discharge_metrics_df.to_csv(discharge_metrics_csv_path, index=False, encoding="utf-8-sig")

        discharge_score_df = scoring.build_score_table(discharge_metrics_df)
        discharge_scores_csv_path = config.output_dir / "discharge_station_scores.csv"
        discharge_score_df.to_csv(discharge_scores_csv_path, index=False, encoding="utf-8-sig")
        discharge_score_table_png_path = config.output_dir / "discharge_score_table.png"
        scoring.render_score_table_png(
            discharge_score_df,
            discharge_score_table_png_path,
            columns=scoring.DISCHARGE_SCORE_COLUMNS,
            mean_columns=scoring.DISCHARGE_SUMMARY_MEAN_COLUMNS,
            title="観測所別 流量 総合評価スコア表",
        )

        if not discharge_metrics_df.empty:
            with_data = discharge_metrics_df[discharge_metrics_df["n_points"] > 0]
            if not with_data.empty:
                print(
                    f"[discharge] avg NSE={with_data['nse'].mean():.3f},"
                    f" avg KGE={with_data['kge'].mean():.3f}"
                    f" over {len(with_data)} stations with data"
                )
        print(f"discharge metrics -> {discharge_metrics_csv_path}")
        print(f"discharge scores -> {discharge_scores_csv_path}")
        print(f"discharge score table -> {discharge_score_table_png_path}")
        print(f"discharge plots -> {discharge_plots_dir}")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=str(Path(__file__).parent / "config" / "hii_202107.yaml"),
        help="設定YAMLファイルへのパス (既定: config/hii_202107.yaml)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="詳細ログを表示する")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    return run(args.config)


if __name__ == "__main__":
    sys.exit(main())
