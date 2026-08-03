"""比較ツールの設定 (YAML) 読み込み。

パスはすべて、このツールのルートディレクトリ (`05_Validate_RIVER1DH/`、
`compare_stations.py` が置かれている場所) からの相対パスとして解決する。
YAML自身の置き場所 (`config/`) には依存しない。これにより、どのディレクトリ
から実行しても (例: 別のcwdから `--config /abs/path/to/hii_202107.yaml`
を叩いても) 一貫して同じ場所を指す。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

# river1dh_validate/config.py -> river1dh_validate/ -> 05_Validate_RIVER1DH/
TOOL_ROOT_DIR = Path(__file__).resolve().parent.parent


@dataclass
class MatchConfig:
    # 観測所から最も近い断面点までの距離がこれを超える場合、その観測所は
    # 「半径 max_distance_m 以内に断面点 (=観測所) が無い」としてマッチ対象から
    # 除外する (unmatched_stations.csv に reason=no_cross_section_within_max_distance
    # で記録される。警告に留めるのではなくハードな足切り)。
    max_distance_m: float = 200.0


@dataclass
class ValidationConfig:
    event_name: str
    result_dir: Path
    waterlevel_csv: str
    wis_output_dir: Path
    water_system: str
    output_dir: Path
    match: MatchConfig
    discharge_csv: Optional[str] = None

    @property
    def waterlevel_csv_path(self) -> Path:
        return self.result_dir / self.waterlevel_csv

    @property
    def discharge_csv_path(self) -> Optional[Path]:
        """流量比較を行う場合の入力CSVパス。`discharge_csv` 未設定なら None
        (=流量比較をスキップし、水位比較のみ行う。後方互換のため必須にしない)。"""
        if not self.discharge_csv:
            return None
        return self.result_dir / self.discharge_csv


def load_config(path: str | Path) -> ValidationConfig:
    config_path = Path(path).resolve()
    with open(config_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    def resolve(rel: str) -> Path:
        return (TOOL_ROOT_DIR / rel).resolve()

    match_raw = raw.get("match", {}) or {}
    match = MatchConfig(
        max_distance_m=float(match_raw.get("max_distance_m", 200.0))
    )

    return ValidationConfig(
        event_name=raw["event_name"],
        result_dir=resolve(raw["result_dir"]),
        waterlevel_csv=raw["waterlevel_csv"],
        wis_output_dir=resolve(raw["wis_output_dir"]),
        water_system=raw["water_system"],
        output_dir=resolve(raw["output_dir"]),
        match=match,
        discharge_csv=raw.get("discharge_csv"),
    )
