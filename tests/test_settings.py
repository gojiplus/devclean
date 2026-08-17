"""Tests for user configuration."""

from devclean.settings import DevCleanConfig, load_config, save_config


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
