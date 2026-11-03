# lets every test file import from src (draft, group, etc) without adding its own sys.path line
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
