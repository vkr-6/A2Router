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
