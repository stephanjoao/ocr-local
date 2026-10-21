"""Run wrapper to ensure workflow module is found correctly."""
import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
    print(f'Added to PYTHONPATH: {PROJECT_ROOT}')

os.environ['PYTHONPATH'] = str(PROJECT_ROOT)
