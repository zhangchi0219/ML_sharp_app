"""Run a temporary local server for manual/browser acceptance. No user data is read."""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
with tempfile.TemporaryDirectory(prefix='sharp-acceptance-') as root:
    os.environ['SHARP_DATA_DIR'] = root
    import uvicorn
    from app import main, db
    try:
        uvicorn.run(main.app, host='127.0.0.1', port=8765)
    finally:
        if db._engine is not None:
            db._engine.dispose()
