# Verification

Current scope: [clean UI/calibration/packaging report](upgrade-report.md).

- Linux Python/Qt: 141 passed, 13 skipped.
- Selected existing Windows Python/PowerShell control/helper tests: 80 passed.
- Native CTest: 1/1 passed on Linux.
- Frozen Linux GUI and offline synthetic FFT runtime checks passed.
- Linux tar.gz/.deb built; neither package installed.
- Windows portable/setup build scripts parsed; Windows native/setup compilation
  and acoustic hardware verification remain pending.

Simulations and synthetic recordings are clearly separated from real native audio
claims. No Windows software or driver was installed during this revision.

CI launcher fixes (2026-10-24):

- Windows staging now includes `.github`, required by the workflow packaging test.
- Private PipeWire tests clear inherited `PULSE_RUNTIME_PATH` and create the
  standard private `pulse` directory before starting daemons, avoiding the
  reported nested `pulse/pulse` startup failure.
- Targeted packaging/environment regressions: 6 passed; Ruff check/format passed.
- Full Windows packaging and live PipeWire execution require a CI rerun;
  the local environment has no PipeWire daemons. RTKit warnings are separate
  from the fatal socket-directory error and do not require elevated audio setup.

Linux property-parser fix (2026-10-24):

- Reproduced corrupted nested `device.description` and ownership properties on
  real PipeWire 0.3.48, using extracted Ubuntu 22.04 packages in a private session.
- Legacy creation now passes the description as a separately quoted top-level
  property and keeps ownership tags in a simple proplist. Verification and
  cleanup checks remain enabled.
- On 0.3.48, names containing both quote types or backslashes are rejected before
  allocation with an upgrade/simpler-name explanation; names with spaces or
  either quote type retain their exact text. Modern quoting is unchanged.
- `dbus-run-session -- python tests/run_private_pipewire.py`: 3 passed on
  PipeWire 0.3.48 and 3 passed on PipeWire 1.0.5 (temporary extracted runtimes).
  Includes mono/stereo/5.1/7.1, real PCM fan-out/mixing, GUI operations, server
  restart restoration, ownership and cleanup. No physical playback was tested.
- Full Python suite: 150 passed, 13 skipped. Ruff check/format passed.
- No audio service, Windows software or driver was installed; all private
  daemons and managed test resources were cleaned up by the harness.
