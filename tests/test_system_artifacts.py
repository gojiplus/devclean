"""Tests for conservative macOS system-artifact discovery."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from devclean.candidates import Tier
from devclean.system_artifacts import SystemPaths, _path_in_use, find_system_artifacts


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True)
    return path


def test_detects_stale_toolchains_and_retained_artifacts(tmp_path):
    usr_local = tmp_path / "usr-local"
    library = tmp_path / "Library"
    opt = tmp_path / "opt"
    temp = tmp_path / "T"
    temp.mkdir()

    tex_2022 = _mkdir(usr_local / "texlive/2022")
    tex_2025 = _mkdir(usr_local / "texlive/2025")
    tex_link = library / "TeX/Distributions/.DefaultTeX/Contents/Root"
    tex_link.parent.mkdir(parents=True)
    tex_link.symlink_to(tex_2025)

    r_old = _mkdir(library / "Frameworks/R.framework/Versions/4.5-arm64")
    r_current = _mkdir(library / "Frameworks/R.framework/Versions/4.6-arm64")
    (r_current.parent / "Current").symlink_to(r_current)

    python_framework = _mkdir(library / "Frameworks/Python.framework/Versions/3.11")
    global_python = _mkdir(opt / "homebrew/lib/python3.11/site-packages")
    installer = opt / "homebrew/Caskroom/mactex/2025.0308/mactex.pkg"
    installer.parent.mkdir(parents=True)
    installer.touch()
    macports = _mkdir(opt / "local")
    chrome_clone = _mkdir(
        tmp_path / "X/com.google.Chrome.code_sign_clone/code_sign_clone.stale"
    )
    obsolete_extension = _mkdir(
        tmp_path / "home/.vscode/extensions/example.extension-1.0.0"
    )
    (obsolete_extension.parent / ".obsolete").write_text(
        json.dumps({obsolete_extension.name: True, "missing.extension-1.0.0": True}),
        encoding="utf-8",
    )

    layout = SystemPaths(
        usr_local=usr_local,
        library=library,
        opt=opt,
        home=tmp_path / "home",
        temp_roots=(temp,),
    )
    size = 200 * 1024 * 1024
    with (
        patch("devclean.system_artifacts.shutil.which", return_value="/bin/python3"),
        patch("devclean.system_artifacts._path_in_use", return_value=False),
    ):
        result = find_system_artifacts(lambda _path: size, paths=layout)

    found = {candidate.path for candidate in result}
    assert {
        tex_2022,
        r_old,
        python_framework,
        global_python,
        installer,
        macports,
        chrome_clone,
        obsolete_extension,
    } <= found
    assert tex_2025 not in found
    assert r_current not in found
    assert all(candidate.tier is Tier.INSPECT for candidate in result)
    assert all(not candidate.bulk_deletable for candidate in result)


def test_chrome_clone_in_use_is_explicitly_blocked(tmp_path):
    temp = _mkdir(tmp_path / "T")
    clone = _mkdir(
        tmp_path / "X/com.google.Chrome.code_sign_clone/code_sign_clone.live"
    )
    layout = SystemPaths(
        usr_local=tmp_path / "usr-local",
        library=tmp_path / "Library",
        opt=tmp_path / "opt",
        home=tmp_path / "home",
        temp_roots=(temp,),
    )

    with patch("devclean.system_artifacts._path_in_use", return_value=True):
        result = find_system_artifacts(lambda _path: 200 * 1024 * 1024, paths=layout)

    candidate = next(item for item in result if item.path == clone)
    assert "currently in use" in candidate.concerns[0]


@patch("devclean.system_artifacts.subprocess.run")
def test_lsof_output_proves_use_even_when_lsof_exits_one(mock_run):
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="COMMAND PID NAME\nChrome 123 /tmp/clone/Chrome\n",
    )

    assert _path_in_use(Path("/tmp/clone")) is True


def test_small_obsolete_extensions_are_reported_when_large_together(tmp_path):
    extensions = tmp_path / "home/.vscode/extensions"
    first = _mkdir(extensions / "example.first-1.0.0")
    second = _mkdir(extensions / "example.second-1.0.0")
    (extensions / ".obsolete").write_text(
        json.dumps({first.name: True, second.name: True}), encoding="utf-8"
    )
    layout = SystemPaths(
        usr_local=tmp_path / "usr-local",
        library=tmp_path / "Library",
        opt=tmp_path / "opt",
        home=tmp_path / "home",
    )

    result = find_system_artifacts(
        lambda _path: 60 * 1024 * 1024, min_size_mb=100, paths=layout
    )

    assert {candidate.path for candidate in result} == {first, second}
