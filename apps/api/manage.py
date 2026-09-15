#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""

import os
import sys

from django.core.management import execute_from_command_line


if __name__ == "__main__":
    subcommand = next((arg for arg in sys.argv[1:] if not arg.startswith("-")), None)
    if subcommand == "test":
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.test")
    else:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    execute_from_command_line(sys.argv)
