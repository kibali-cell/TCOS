#!/usr/bin/env python
"""Django command-line entry point for TCOS."""

import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django is not installed. Activate the virtual environment or use Docker."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
