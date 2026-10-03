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


def _env_overrides() -> tuple[dict[str, Any], dict[str, Any]]:
    import os

    server: dict[str, Any] = {}
    if os.environ.get("IRLDS_HOST"):
        server["host"] = os.environ["IRLDS_HOST"]
    if os.environ.get("IRLDS_PORT"):
        server["port"] = int(os.environ["IRLDS_PORT"])
    log: dict[str, Any] = {}
    if os.environ.get("IRLDS_LOG_LEVEL"):
        log["level"] = os.environ["IRLDS_LOG_LEVEL"]
    return server, log


def _validate(cfg: Config) -> Config:
    if not (0 <= cfg.server.port <= 65535):
        raise ValueError(f"server.port out of range: {cfg.server.port}")
    if cfg.scraper.poll_hz <= 0:
        raise ValueError(f"scraper.poll_hz must be > 0: {cfg.scraper.poll_hz}")
    for name in ("key_sequence", "fallback_key_sequence"):
        seq = getattr(cfg.pit_actions, name)
        if not isinstance(seq, list) or not all(
            isinstance(step, list) and step and all(isinstance(k, str) for k in step) for step in seq
        ):
            raise ValueError(f"pit_actions.{name} must be a list of non-empty lists of key names")
    if not isinstance(cfg.server.allowed_origins, list):
        raise ValueError("server.allowed_origins must be a list")
    return cfg


def load_config(path: str = "config.toml") -> Config:
    """Load config.toml (missing file = defaults), then apply IRLDS_* env overrides."""
    raw: dict[str, Any] = {}
    p = Path(path)
    if p.exists():
        if tomllib is None:
            raise RuntimeError("tomllib / tomli is required to load config")
        with open(p, "rb") as f:
            raw = tomllib.load(f)

    server_overrides, log_overrides = _env_overrides()
    return _validate(Config(
        server=_parse_section(raw.get("server", {}), ServerConfig, server_overrides or None),
        scraper=_parse_section(raw.get("scraper", {}), ScraperConfig),
        pit_actions=_parse_section(raw.get("pit_actions", {}), PitActionsConfig),
        logging=_parse_section(raw.get("logging", {}), LoggingConfig, log_overrides or None),
    ))
