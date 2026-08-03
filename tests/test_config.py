from __future__ import annotations

from pathlib import Path

from river1dh_validate.config import TOOL_ROOT_DIR, load_config


def _write_yaml(tmp_path: Path, extra: str = "") -> Path:
    yaml_path = tmp_path / "test_config.yaml"
    yaml_path.write_text(
        f"""
event_name: TestEvent
result_dir: ../03_Result/TestEvent
waterlevel_csv: timeseries_of_waterlevel_river1dh.csv
{extra}
wis_output_dir: ../../Download_WIS/output
water_system: 斐伊川
match:
  max_distance_m: 150
output_dir: output/TestEvent
""",
        encoding="utf-8",
    )
    return yaml_path


def test_load_config_without_discharge_csv_leaves_it_none(tmp_path):
    yaml_path = _write_yaml(tmp_path)

    config = load_config(yaml_path)

    assert config.event_name == "TestEvent"
    assert config.discharge_csv is None
    assert config.discharge_csv_path is None
    assert config.match.max_distance_m == 150


def test_load_config_with_discharge_csv_resolves_path(tmp_path):
    yaml_path = _write_yaml(tmp_path, extra="discharge_csv: timeseries_of_discharge_river1dh.csv")

    config = load_config(yaml_path)

    assert config.discharge_csv == "timeseries_of_discharge_river1dh.csv"
    assert config.discharge_csv_path == config.result_dir / "timeseries_of_discharge_river1dh.csv"


def test_load_config_resolves_paths_relative_to_tool_root(tmp_path):
    yaml_path = _write_yaml(tmp_path)

    config = load_config(yaml_path)

    assert config.result_dir == (TOOL_ROOT_DIR / "../03_Result/TestEvent").resolve()
    assert config.output_dir == (TOOL_ROOT_DIR / "output/TestEvent").resolve()
    assert config.waterlevel_csv_path == config.result_dir / "timeseries_of_waterlevel_river1dh.csv"
