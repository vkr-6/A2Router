# Test a clean source checkout

Extract `A2Router-source.zip` and open its `A2Router` directory. Generated dependencies and executables are deliberately absent. Internet access is needed to install Python dependencies. No Docker VM is required.

## Windows 10/11 x64

Install Python 3.12 x64, Visual Studio 2022 Build Tools with Desktop C++ and a Windows SDK, and CMake. In a Developer PowerShell, from the project root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[test,build]"
cmake -S . -B build -A x64
cmake --build build --config Release --parallel
ctest --test-dir build -C Release --output-on-failure
$env:QT_QPA_PLATFORM = "offscreen"
$env:A2ROUTER_WASAPI_NATIVE = "1"
.venv\Scripts\python -m pytest -q
Remove-Item Env:\QT_QPA_PLATFORM
.venv\Scripts\python -m a2router diagnostics
.venv\Scripts\python -m a2router gui
```

For portable executables, from Developer PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File tools/windows/build-portable.ps1
```

Outputs are generated in `dist/windows-x64/` and `dist/a2router-windows-x64.zip`; intermediate Windows files default to `%LOCALAPPDATA%\a2router-build`. Use `-Workspace C:\your\build-folder` to choose their location. No compiler downloads or VM are needed when Visual Studio is installed.

In the GUI inspect devices, then test an output loopback to another output using low-volume audio. Avoid routes that return audio to its source. Microphone monitoring needs explicit confirmation; use headphones to avoid feedback. Verify enable/disable, multiple destinations and configuration restoration on your hardware. Windows virtual audio uses the unchanged VB-CABLE package bundled in the portable ZIP and installed only from Create output in Virtual devices; see `drivers/windows/README.md`. Actual installation requires a separate target-machine check. The VM-only PCM test is opt-in and is not intended for ordinary desktops.

## Native Linux / PipeWire

On Ubuntu/Debian:

```bash
sudo apt install python3-venv pipewire pipewire-pulse wireplumber pulseaudio-utils cmake g++
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m pytest -q
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure
python -m a2router diagnostics
python -m a2router gui
```

Create a stereo virtual device, select it as an application's output, then route its monitor to your speakers/headphones. Additional routes provide additional destinations. Save a configuration and check restoration. Optional isolated real-server integration:

```bash
dbus-run-session -- python tests/run_private_pipewire.py
```

That test creates private servers and temporary virtual endpoints; it does not validate physical speakers. See `docs/verification.md` for previous observed results and limitations. Standard tests use offscreen Qt and skip opt-in platform integration tests.

## Optional channel routing

Run `ctest` for float identity, swaps, duplication, unmapped silence, summing/clipping and PCM16/24/32 decoding tests. Python tests validate matrix shapes/gains, ABI serialization, disabled/reenabled routes, profile restoration and no-restart polling. These checks do not verify WASAPI output formats on a real Windows endpoint. On a suitable target, use a low-level stereo signal to check channel order, duplication, gain and clipping telemetry. No driver installation should be needed if VB-CABLE is already present.

## Endpoint configuration and main-page controls

Simulated tests cover adapter branding classification, 16-channel format selection, source/destination editor refresh, master-volume/mute calls without source restarts, exact-format membership, active-route guards, system renaming, graph history/availability and device filters. The Windows bridge build check requires all new exports. On a separate suitable target, verify actual name changes in another application and exact device/default/mix formats after Apply; test both playback and recording sides. This session does not install or change Windows devices.
