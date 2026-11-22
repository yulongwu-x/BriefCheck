"""Allow running BriefCheck via `python -m briefcheck`."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
