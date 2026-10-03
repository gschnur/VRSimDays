from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # Python 3.10 fallback
    except ImportError:
        tomllib = None  # type: ignore[assignment]


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    allowed_origins: list[str] = field(default_factory=list)


@dataclass
class ScraperConfig:
    poll_hz: int = 60
    count_outlap: bool = False


@dataclass
class PitActionsConfig:
    enabled: bool = True
    window_title: str = "iRacing.com Simulator"
    key_sequence: list[list[str]] = field(default_factory=lambda: [["alt", "r"]])
    fallback_key_sequence: list[list[str]] = field(default_factory=list)
    pre_delay_ms: int = 150
    failsafe: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"
    file: str = "irlds.log"


@dataclass
class Config:
    server: ServerConfig = field(default_factory=ServerConfig)
    scraper: ScraperConfig = field(default_factory=ScraperConfig)
    pit_actions: PitActionsConfig = field(default_factory=PitActionsConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _parse_section(d: dict[str, Any], cls: type, overrides: dict[str, Any] | None = None) -> Any:
    kwargs: dict[str, Any] = {}
    init_params = {p.name for p in cls.__dataclass_fields__.values()}
    for key, value in d.items():
        if key in init_params:
            kwargs[key] = value
    if overrides:
        for k, v in overrides.items():
            if k in init_params:
                kwargs[k] = v
    return cls(**kwargs)


def load_config(path: str = "config.toml") -> Config:
    import os

    if tomllib is None:
        raise RuntimeError("tomllib / tomli is required to load config")

    p = Path(path)
    if not p.exists():
        return Config()

    with open(p, "rb") as f:
        raw = tomllib.load(f)

    server_overrides = {
        "host": os.environ.get("IRLDS_HOST"),
        "port": int(os.environ["IRLDS_PORT"]) if "IRLDS_PORT" in os.environ else None,
    }
    server_overrides = {k: v for k, v in server_overrides.items() if v is not None}

    log_overrides = {}
    ll = os.environ.get("IRLDS_LOG_LEVEL")
    if ll:
        log_overrides["level"] = ll

    return Config(
        server=_parse_section(raw.get("server", {}), ServerConfig, server_overrides or None),
        scraper=_parse_section(raw.get("scraper", {}), ScraperConfig),
        pit_actions=_parse_section(raw.get("pit_actions", {}), PitActionsConfig),
        logging=_parse_section(raw.get("logging", {}), LoggingConfig, log_overrides or None),
    )
