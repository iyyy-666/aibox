# Final Review Fix Report

Date: 2026-09-28

## Findings Resolved

- Preserved zero-distance protocol nodes in complete rotations for scan framing and alignment.
- Split device diagnostics into structural node counts and positive-return counts. `valid_points`, `last_frame_positive_points`, the displayed point rate, and the displayed last-frame point count now describe positive-distance returns.
- Changed the configurable `minimum_frame_points` default from 1 to 10 positive returns. Zero-only and undersized frames no longer advance readiness or enter the baseline buffer.
- Corrected the detection-region inner arc endpoint to the official radar transform: `x = sin(angle) * r`, `y = -cos(angle) * r`.
- Added the effective `detection_region` to scan and detection events. The frontend now updates its rendered region from either event payload, including detection events without scan points.
- Preserved manual-only搬运 behavior; no automatic movement action was added.

## Regression Coverage

- Device tests verify that zero-distance nodes remain in yielded rotations while positive and structural diagnostics remain distinct.
- Worker tests verify the default 10-return threshold, rejection of zero-only and undersized frames, positive-return scan output/diagnostics, and detection-region payloads.
- Frontend contract tests verify the canonical arc transform and backend-driven region state for scan and detection events.

## Verification

- Focused: `python -m pytest -q tests/test_radar_core.py tests/test_radar_worker.py tests/test_radar_frontend_contract.py`
  - Result: `53 passed in 0.78s`
- Full: `python -m pytest -q`
  - Result: `290 passed, 1 warning in 55.33s`
  - Warning: existing `StarletteDeprecationWarning` for the `httpx`/`starlette.testclient` compatibility path.
