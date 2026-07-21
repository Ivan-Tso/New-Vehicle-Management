import sys
import os

# ============================================================
# WSGI entry point for PythonAnywhere
# ============================================================

PROJECT_DIR = '/home/IvanTso/vehicle-management'

if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

os.chdir(PROJECT_DIR)

from app import application as app # noqa: E402
