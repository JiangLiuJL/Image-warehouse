import sys
from pathlib import Path

import pdd_art_manager.config as config


def test_project_root_uses_source_root_when_not_frozen() -> None:
    assert config.get_project_root() == Path(__file__).resolve().parents[1]


def test_config_uses_executable_directory_when_frozen(monkeypatch) -> None:
    fake_executable = Path(r"D:\apps\ImageWarehouse\ImageWarehouse.exe")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_executable))
    assert config.get_project_root() == fake_executable.parent
