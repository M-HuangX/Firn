"""API package — shared constants."""

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # api/ -> src/ -> project root
LOGS_DIR = PROJECT_ROOT / "logs"
FIRN_ROOT = PROJECT_ROOT / "firn"
KB_ROOT = FIRN_ROOT  # alias for backward compatibility
