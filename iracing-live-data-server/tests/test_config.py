from __future__ import annotations

from pathlib import Path

import pytest

from irlds.config import load_config


def test_missing_file_gives_defaults(tmp_path: Path) -> None:
    cfg = load_config(str(tmp_path / "nope.toml"))
    assert cfg.server.port == 8765
    assert cfg.pit_actions.key_sequence == [["alt", "r"]]


def test_env_overrides_apply_without_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IRLDS_PORT", "9000")
    monkeypatch.setenv("IRLDS_HOST", "0.0.0.0")
    monkeypatch.setenv("IRLDS_LOG_LEVEL", "DEBUG")
    cfg = load_config(str(tmp_path / "nope.toml"))
    assert (cfg.server.host, cfg.server.port, cfg.logging.level) == ("0.0.0.0", 9000, "DEBUG")


def test_loads_file(tmp_path: Path) -> None:
    p = tmp_path / "c.toml"
    p.write_text('[server]\nport = 1234\nallowed_origins = ["null"]\n[pit_actions]\nkey_sequence = [["shift", "p"]]\n')
    cfg = load_config(str(p))
    assert cfg.server.port == 1234
    assert cfg.server.allowed_origins == ["null"]
    assert cfg.pit_actions.key_sequence == [["shift", "p"]]


@pytest.mark.parametrize(
    "body",
    ['[server]\nport = 70000\n', '[scraper]\npoll_hz = 0\n', '[pit_actions]\nkey_sequence = ["alt+r"]\n'],
)
def test_invalid_values_rejected(tmp_path: Path, body: str) -> None:
    p = tmp_path / "c.toml"
    p.write_text(body)
    with pytest.raises(ValueError):
        load_config(str(p))


def test_repo_config_loads() -> None:
    cfg = load_config(str(Path(__file__).parent.parent / "config.toml"))
    assert cfg.server.host == "127.0.0.1"
