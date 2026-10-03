import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="irlds",
        description="iRacing Live Data Server",
    )
    parser.add_argument(
        "--config",
        default="config.toml",
        help="Path to config.toml (default: config.toml)",
    )
    parser.add_argument(
        "--fake-source",
        action="store_true",
        help="Use fake telemetry source instead of iRacing",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Override log level",
    )
    args = parser.parse_args()

    from irlds.config import load_config
    from irlds.logging_setup import setup_logging

    config = load_config(args.config)
    if args.log_level:
        config.logging.level = args.log_level
    setup_logging(config.logging.level, config.logging.file or None)

    import logging

    log = logging.getLogger("irlds")
    log.info("IRLDS starting (config=%s, fake_source=%s)", args.config, args.fake_source)

    from irlds.app import IRLDSApp

    app = IRLDSApp(config, fake_source=args.fake_source)
    try:
        app.run()
    except KeyboardInterrupt:
        log.info("Shutting down (Ctrl+C)")
        app.stop()
        sys.exit(0)


if __name__ == "__main__":
    main()
