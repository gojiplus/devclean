"""Tests for user configuration."""

from devclean.settings import DevCleanConfig, create_sample_config, load_config, save_config


def test_loads_temporary_directory_scan_setting(tmp_path):
    config_path = tmp_path / ".devclean.toml"
    config_path.write_text("[scan]\ninclude_temporary_dirs = false\n", encoding="utf-8")

    config = load_config(config_path)

    assert config.scan.include_temporary_dirs is False


def test_saves_temporary_directory_scan_setting(tmp_path):
    config = DevCleanConfig()
    config.scan.include_temporary_dirs = False
    config_path = tmp_path / ".devclean.toml"

    save_config(config, config_path)

    assert load_config(config_path).scan.include_temporary_dirs is False


def test_loads_project_scan_and_system_settings(tmp_path):
    config_path = tmp_path / ".devclean.toml"
    config_path.write_text(
        "additional_search_paths = ['~/work']\n"
        "[scan]\n"
        "include_system_artifacts = false\n"
        "max_depth = 11\n"
        "timeout_seconds = 45\n",
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.additional_search_paths == ["~/work"]
    assert config.scan.include_system_artifacts is False
    assert config.scan.max_depth == 11
    assert config.scan.timeout_seconds == 45


def test_sample_config_keeps_project_paths_at_top_level(tmp_path):
    config_path = tmp_path / ".devclean.toml"

    create_sample_config(config_path)
    config = load_config(config_path)

    assert config.additional_search_paths == ["~/workspace", "~/coding"]
    assert config.scan.include_system_artifacts is True
    assert config.scan.max_depth == 8
    assert config.scan.timeout_seconds == 120
