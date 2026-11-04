"""Run real SHARP smoke and equivalence checks in an isolated temporary directory."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='sharp-model-validation-') as data:
    env = {**os.environ, 'SHARP_DATA_DIR': data,
           'SHARP_EQUIV_DIR': str(Path(data) / 'equivalence'), 'PYTHONIOENCODING': 'utf-8'}
    for script in ('backend/smoke.py', 'scripts/verify_equivalence.py'):
        subprocess.run([sys.executable, str(root / script)], cwd=root, env=env, check=True)
