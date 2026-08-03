# 05_Validate_RIVER1DH

RIVER1DHソルバーの計算結果 (河道断面ごとの水位時系列) と、実際の観測所
(国土交通省 水文水質データベース; [Download_WIS](../../Download_WIS) が
スクレイピングした出力) を比較するツール。

現状は Hii_202107 (斐伊川2021年7月豪雨) のみを対象としている。

## セットアップ

```bash
cd 05_Validate_RIVER1DH
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

前提として [Download_WIS](../../Download_WIS) 側で以下が生成済みであること:

- `output/water_level_discharge_stations.csv` (観測所メタデータ)
- `output/timeseries/<station_id>.csv` (観測所ごとの時刻水位、比較したい期間を含むもの)
- `output/timeseries_discharge/<station_id>.csv` (観測所ごとの時刻流量。
  流量比較を行いたい場合のみ必要。`python main.py --timeseries-discharge` で取得する)

## 実行方法

```bash
python compare_stations.py --config config/hii_202107.yaml
```

## 設定 (YAML)

`config/hii_202107.yaml` にどのソルバー結果 (`03_Result/` 以下のどのフォルダ)
を対象にするかを記述する。別の実行結果と比較したい場合は、このファイルを
コピーして `result_dir` / `waterlevel_csv` / `output_dir` を書き換えるだけでよい
(`river_point.gpkg` のパスはハードコードしていない。対象のCSVの1行目に
ソルバー自身が書き出したパスが入っているので、そこから自動的に解決する)。

```yaml
event_name: Hii_202107_coupled_test
result_dir: ../03_Result/Hii_202107_coupled_test
waterlevel_csv: timeseries_of_waterlevel_river1dh.csv
# 省略可: 設定すると流量の比較も追加で実行される (無ければ水位比較のみ)
discharge_csv: timeseries_of_discharge_river1dh.csv
wis_output_dir: ../../Download_WIS/output
water_system: 斐伊川
match:
  max_distance_m: 200
output_dir: output/Hii_202107_coupled_test
```

## マッチングの考え方

1. `water_level_discharge_stations.csv` から `water_system` が一致する観測所を抽出する。
2. ソルバー側の `river_point.gpkg` から `河川名 -> 河川コード(W05_002)` の対応表を作る。
   **1つの河川名が複数の河川コードに対応している場合は、データ構造上あって
   はならない状態としてエラーで停止する** (静かに無視しない)。
3. 各観測所について、`river_name` が一致する断面点だけに候補を絞り、
   観測所の緯度経度 (WGS84) をGPKGの座標系に変換したうえで最近傍点を採用する。
   - 観測所の `river_name` がGPKGに存在しない場合 (例: 宍道湖・中海・神戸川など、
     1D河道ネットワークの対象外にある水系) は、エラーではなく「未マッチ」として
     `unmatched_stations.csv` に記録する (reason=`river_not_in_network`)。
   - 緯度経度が無い観測所 (廃止済みで位置情報が欠けているものなど) も同様に
     未マッチ扱い (reason=`no_coordinates`)。
   - 最も近い断面点までの距離が `match.max_distance_m` (既定200m) を超える場合、
     「半径 `max_distance_m` 以内に断面点 (=観測所) が無い」とみなしてハードに
     除外する (reason=`no_cross_section_within_max_distance`。警告に留めず、
     `comparison_metrics.csv` には含めず `unmatched_stations.csv` 側に回す。
     見つかった最近傍点までの実際の距離は `unmatched_stations.csv` の
     `nearest_distance_m` 列で確認できる)。
4. マッチした観測所ごとに、水位を比較可能にするため T.P. 標高に変換する:
   `観測水位(TP) = water_level_m + detail_gauge_zero_m`
   (流量は零点高による変換が不要なため、`discharge_m3s` の値をそのまま使う)
5. ソルバー出力 (10分間隔) を観測タイムスタンプ (観測所や年代によりまちまち、
   古いデータは1時間間隔が多い) の上に線形補間して誤差指標を計算する。
6. `discharge_csv` を設定している場合、水位で確定した観測所⇔断面点(`i_ID`)の
   マッチング結果をそのまま再利用し、流量についても同様に指標を計算する
   (マッチングは変量に依存しない、同じ物理的な断面点を指すため)。

## 評価指標セット

洪水時の水位・流量比較における基本指標セット (実運用でのユーザー確認済み):

| 変量 | 基本指標 |
| --- | --- |
| 水位 | RMSE, Bias, ピーク値差, ピーク時刻差 (総合評価はNSEベース) |
| 流量 | NSE, KGE, PBIAS, ピーク値差, ピーク時刻差, 総量差 |

- **KGE** (Kling-Gupta Efficiency): 相関・変動比・バイアス比の3成分に分解した
  総合効率指標。KGE=1が完全一致。`obs` が定数 (標準偏差または平均が0) の
  観測所では定義できないため `None` になる。
- **PBIAS** (%): `100 × Σ(obs - sim) / Σ(obs)`。正の値はモデルの過小評価、
  負の値は過大評価を意味する (Moriasi et al., 2007 の定義)。
- **総量** (`obs_volume_m3` / `sim_volume_m3` / `volume_diff_percent`): 観測期間
  内の流量を台形積分した総流出量 [m3] と、その相対誤差 [%]。

これらは水位・流量どちらの比較でも `comparison_metrics.csv` 系の出力に
一律で含まれる (計算コストが低いため)。どの指標を主にスコア表へ載せるかは
変量ごとに `river1dh_validate/scoring.py` の
`WATERLEVEL_SCORE_COLUMNS` / `DISCHARGE_SCORE_COLUMNS` で切り替えている。

## 出力

`<output_dir>/` 以下:

### 水位

- `comparison_metrics.csv` — マッチした観測所ごとの RMSE・MAE・Bias・NSE・KGE・
  PBIAS・ピーク水位差・ピーク時刻差・総量・マッチ距離など (全指標を含む)。
- `unmatched_stations.csv` — マッチしなかった観測所と理由 (`river_not_in_network` /
  `no_coordinates` / `no_cross_section_within_max_distance`)。
- `station_scores.csv` — `comparison_metrics.csv` に総合評価 (`index_score`) と
  表示色 (`index_color`) の列を加えたもの。
- `score_table.png` — 観測所別の水位総合評価 (RMSE/Bias/ピーク/時刻/NSE) を
  色分けした一覧表 (NSEの良い順に並び、最終行に全観測所を通した「全体の」
  平均指標が入る)。総合評価は NSE を Moriasi et al. (2007) の評価区分
  (Very good / Good / Satisfactory / Unsatisfactory) に当てはめたもの。
- `plots/<station_id>_<station_name>.png` — 水位の観測値 vs シミュレーションの重ね描きグラフ。

### 流量 (`discharge_csv` 設定時のみ)

- `discharge_comparison_metrics.csv` / `discharge_station_scores.csv` — 水位側と
  同じ構造で、流量 (`discharge_m3s`, 単位 m3/s) について計算したもの。
- `discharge_score_table.png` — NSE/KGE/PBIAS/ピーク/総量差を表示した流量版スコア表。
- `plots_discharge/<station_id>_<station_name>.png` — 流量の観測値 vs シミュレーション
  の重ね描きグラフ (NSE/KGE/PBIAS/ピーク/総量差を表示)。

## テスト

```bash
python -m pytest tests/ -q
```
