import sys
from pathlib import Path

# Add project root to sys.path so all modules are importable during tests
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
