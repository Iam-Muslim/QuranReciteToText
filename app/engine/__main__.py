"""CLI execution module for app.engine."""
import sys
from pathlib import Path

_APP_DIR = Path(__file__).parent.parent.resolve()
if str(_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_APP_DIR))

from engine.server import run_server

if __name__ == "__main__":
    run_server()
