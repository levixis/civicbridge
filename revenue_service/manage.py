from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os, sys

if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "revenue_config.settings")
    from django.core.management import execute_from_command_line

    execute_from_command_line(sys.argv)
