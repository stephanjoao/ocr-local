"""Caderno de receitas local. Module root."""
import os
import sys

# Ensure project root is in sys.path for workflow module to be found
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)