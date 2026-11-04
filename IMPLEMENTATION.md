# SHARP repair and workbench implementation

Source: user supplied plan (2026-10-27).

- Backend: shared image decoding, bounded uploads, transactional file cleanup, worker execution, mutation coordination, UTC serialization.
- Frontend: legacy parameter normalization, connection polling, submission guards, persistent previews, viewer lifecycle, three column responsive workspace.
- Validation: isolated regressions, real SHARP smoke/equivalence, browser scenarios and screenshots, build and diff checks.

Ruling: implement in the existing feature checkout `feat/lod-splat-export` to preserve the shared local runtime and installed model dependencies; test data uses temporary directories. No history migration or bulk cleanup.

Pre-flight: history parameter types feed the panel and summaries; normalization must retain legacy density only for display and filter it from generation requests. Generation and deletion share source paths and require the same process lock.

Progress: implementation complete; final checks passed.

Validation:
- Backend: 8 isolated unittest regressions pass (HEIC, RGB modes, all EXIF orientations and pixels, invalid/40MB uploads, partial export cleanup, commit rollback, shared source/thumb lifecycle, regenerate/delete coordination, serial inference).
- Frontend: 3 parameter regressions pass; 8 browser acceptance scenarios pass with zero unhandled errors. Additional browser checks cover model loading/error states, failed deletion, unavailable WebGL, full precision switching and download.
- Real model: SMOKE-OK and EQUIV-OK. PLY 1,179,648 points / 66,061,086 bytes; SPLAT 294,912 points / 9,437,184 bytes. Warm inference 1.05-1.15 seconds on RTX 5080. Timings are observations, not performance guarantees.
- Live API: health 61 ms and history 64 ms while regeneration finished at 1199 ms; all HTTP 200. UTC timestamp suffix +00:00.
- Layout: 1440x900, 960x640 and 390x844 have no horizontal overflow, one active canvas; below1080 preview precedes parameters and history.
- Build and git diff --check pass. Fresh review found no remaining important issues after viewer error disposal fix.

Commands:
```
.venv/Scripts/python.exe -m unittest discover -s backend -p test_regressions.py -v
npm.cmd test --prefix frontend
npm.cmd run build --prefix frontend
.venv/Scripts/python.exe scripts/validate_model.py
```

Browser acceptance: start `scripts/validation_server.py`, upload a sample in http://127.0.0.1:8765, then run `scripts/browser_acceptance.js` with the Playwright browser_run_code_unsafe filename argument. It injects controlled failures and restores normal routing. The server and model checks use temporary data, never the existing database.

Screenshots: `.playwright-mcp/real-preview-1440.png`, `real-preview-960.png`, `real-preview-390.png`.

Limits: browser acceptance used Chromium; the native pywebview/WebView2 window and its Save As dialog were not separately launched. The existing download link/desktop settings are retained. Model and runtime remain unchanged.
