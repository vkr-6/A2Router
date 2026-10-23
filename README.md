# A2Router — Advanced Audio Router

A compact desktop application for routing audio from multiple sources to multiple outputs. The interface uses Python and Qt Widgets; audio transport runs in PipeWire on Linux and the native C++ WASAPI engine on Windows.

**Built on [vkr-6/MultiRoute](https://github.com/vkr-6/MultiRoute), originally [FulminataXII/MultiRoute](https://github.com/FulminataXII/MultiRoute). Developed with OpenAI Codex under the project owner's direction.** Original engine authorship and Microsoft driver credits are detailed below.

## Features and current status

- Discover inputs, outputs and output monitors, with reported active formats and channel layouts.
- Create, enable, disable and remove concurrent device-level routes; support fan-out and multiple sources per destination.
- Save and restore versioned JSON configurations and profiles, retaining unavailable-device definitions.
- Linux: real PipeWire virtual outputs through `pipewire-pulse`, with mono, stereo, 5.1 and 7.1 layouts; owned-resource cleanup and reconnection support.
- Windows: reuse MultiRoute's WASAPI engine for input capture and output loopbacks, with native drift compensation and telemetry.
- Windows uses the original VB-CABLE base package by VB-Audio for the virtual cable, with live native delay adjustment, persisted requests and readable buffering/drift metrics.

**The setup/install and audio hardware paths need verification on a Windows target.** A2Router setup bundles the original signed VB-CABLE installer; it does not build a custom driver. The base package supplies one shared cable, not arbitrary named devices. Supported active channel layouts/formats are read from Windows. Windows audio signal transport and physical-device/acoustic synchronization remain unverified. Linux virtual-graph PCM transport was verified in earlier isolated-server tests; this does not establish physical-hardware playback coverage. See [verification scope](docs/verification.md).

## Build with GitHub Actions

Push this source tree to your repository. The [A2Router build workflow](.github/workflows/build.yml) is **manual-only**: start it from **Actions → A2Router build → Run workflow**. Pushing commits or opening pull requests does not trigger builds.

| Job | Output / checks |
|---|---|
| Windows x64 portable application | Builds the native engine/helper, runs native and Python checks, packages GUI and CLI EXEs, and performs clearly labelled simulated offscreen startup checks |
| Linux | Python lint/format checks, Python and native tests, isolated real PipeWire integration |
| Windows setup (default enabled) | With **build_setup** enabled, compiles an Inno Setup EXE containing the original VB-CABLE package; installs it automatically when absent |

After a successful run, download from the run's **Artifacts** section:

- **A2Router-windows-x64**: portable GUI/CLI, checksums, runtime notices and build reports. Launch `a2router.exe` after extracting.
- **A2Router-windows-x64-zip**: the same portable application in a distributable ZIP.
- **A2Router-windows-native**: WASAPI DLL, device manager, native CLI and diagnostic tools.
- **A2Router-Setup-x64**: Windows installer, with the original signed VB-CABLE package, vendor license/attribution, checked-by-default driver task, existing-install detection and restart handling.

Hosted Windows runners use the simulated backend for packaged GUI checks and load the actual DLL to verify its ABI. Endpoint-dependent tests are skipped there; local non-headless builds can run endpoint discovery checks. Hosted runners do not prove real speaker playback, microphone capture quality or acoustic synchronization. The workflow does not install drivers, enable test signing, change audio defaults, or publish a release. The updated workflow has not been dispatched during source preparation.

When using a new GitHub repository, point your existing remote at it before pushing:

```bash
git remote set-url origin https://github.com/YOUR_ACCOUNT/A2Router.git
git add .
git diff --cached --stat
git commit -m "Add A2Router application and build workflows"
git push -u origin HEAD
```

Use your actual repository URL. Do not commit generated dependencies, VM images, certificates or build outputs; these are ignored. Local `prompt.md` and `progress.md` continuation notes are retained on disk but excluded from Git and source distributions.

## Linux setup

On a native Ubuntu/Debian PipeWire desktop:

```bash
sudo apt install python3-venv pipewire pipewire-pulse wireplumber pulseaudio-utils
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
python -m a2router diagnostics
python -m a2router gui
```

Run as your normal desktop user. `pactl info` must connect to the intended audio server. In **Virtual devices**, create a named output and select it in the source application's sound settings. In **Routing**, select that virtual output's monitor and a physical destination. Add another route for another output. Matching channel layouts are required; implicit surround downmixing is rejected. Microphone monitoring requires explicit feedback-risk confirmation.

PipeWire supplies transport, mixing and clock management. Adjustable delay is not currently exposed on Linux. See [Linux details](docs/linux.md).

## Windows setup and local build

Install Python 3.12 x64, Visual Studio 2022 with Desktop C++, a Windows SDK and CMake. From the project root:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
cmake -S . -B build -A x64
cmake --build build --config Release
.venv\Scripts\python -m a2router diagnostics
.venv\Scripts\python -m a2router gui
```

The bridge is `build/a2router_wasapi.dll`; `A2ROUTER_WASAPI_DLL` overrides its path. To build portable EXEs from a Visual Studio developer shell:

```powershell
powershell -ExecutionPolicy Bypass -File tools/windows/build-portable.ps1
```

Outputs are `dist/windows-x64/` and `dist/a2router-windows-x64.zip`. The script uses `%LOCALAPPDATA%\a2router-build` for temporary work, or the directory supplied with `-Workspace`. `-Headless` uses simulated packaged smoke checks, skips endpoint-dependent tests and omits native desktop startup; `-SkipTests` skips automated and packaged smoke checks. No Python installation is needed to run the packaged EXEs.

### Windows setup and VB-CABLE

After building the portable EXEs, compile the setup file using Inno Setup 6.3 or later:

```powershell
powershell -ExecutionPolicy Bypass -File tools/windows/build-setup.ps1
```

Output: `dist/setup/A2Router-Setup-x64.exe`. GitHub's manual workflow builds this when **build_setup** is selected (enabled by default). Setup bundles all vendor files unchanged from the supplied `VBCABLE_Driver_Pack45.zip`; the original ZIP is retained in source. The package hash is pinned and its vendor installer's Authenticode signature is checked. The custom WDK driver, device-creation helper and unsigned-driver workflow have been removed.

The default setup task installs VB-CABLE only when absent, with administrator approval. It leaves existing healthy installations unchanged, reports driver failures, and offers a Windows restart after new installation. You can deselect the task. Windows may choose new default sound devices during driver installation: check Sound settings after restarting. A2Router does not explicitly set defaults. A2Router uninstall offers to remove VB-CABLE too. It defaults to removal for a driver installed by A2Router, and to keeping a pre-existing driver; the user can choose either. Driver removal uses the vendor uninstaller and requests a restart. Silent uninstall keeps the driver unless `/REMOVEVBCABLE=1` is explicitly supplied.

**VB-CABLE is donationware by [VB-Audio Software](https://www.vb-cable.com/). Donations and license purchases are welcome.** See [licensing and bundling terms](https://vb-audio.com/Services/licensing.htm); professional deployments may need separate licenses. Original copyright, vendor branding and license files remain intact. A+B and C+D cables are not included.

Select **CABLE Input** as an application's playback device. In A2Router route **CABLE Output** (the recording side) to speakers/headphones. The Virtual devices page displays the actual VB-CABLE endpoints instead of offering fake named-device creation. The 16-channel alternative playback endpoint belongs to the same cable; routing its capture/monitor back to either cable input is blocked as feedback. No driver is installed on application startup or during CI checks.

See [VB-CABLE integration](drivers/windows/README.md).

### Synchronization and stable refresh

Select a route on **Synchronization**, edit the additional delay, then Apply. Draft values survive focus changes and periodic refreshes; Discard restores the saved request. Native live-delay adjustment is used within the current buffer. A larger adjustment can restart that source only if **Allow a source restart** is selected. The page shows route state, requested delay, actual buffer/target, rate correction and underruns. Existing native drift compensation remains automatic; acoustic alignment still requires measurement.

Periodic refresh updates changed cells in place, preserving selections and scroll positions. It does not rebuild lists, flash the Updating message or disable controls. A click made while polling is queued instead of discarded. Polling does not restart healthy routes.

See [Windows details](docs/windows.md) and [clean-machine testing](docs/testing.md).

## Commands and lifecycle

```bash
python -m a2router diagnostics
python -m a2router devices
python -m a2router routes
python -m a2router gui
python -m a2router create-virtual "Application bus" --layout stereo
python -m a2router add-route SOURCE_ID DESTINATION_ID
python -m a2router disable-route ROUTE_UUID
python -m a2router enable-route ROUTE_UUID
python -m a2router remove-route ROUTE_UUID
python -m a2router remove-virtual VIRTUAL_UUID
python -m a2router save studio.json
python -m a2router load studio.json
```

Use device IDs returned by `devices`. Read-only diagnostics do not activate saved routes. `python -m a2router --mock gui` uses a clearly labelled simulation and separate state. Windows CLI processes cannot sustain routing after exit; use the GUI.

Closing the window hides/minimizes it. **Exit controller** leaves Linux server resources running but stops Windows processing. **Stop all managed routes** explicitly disables routes. Configuration restoration creates managed virtual devices before dependent routes; missing endpoints remain pending. Default speakers/microphones are not explicitly changed by the application.

## Development checks

```bash
python -m pip install -e '.[test]'
ruff check a2router tests tools/windows
ruff format --check a2router tests tools/windows
python -m pytest -q
cmake -S . -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --parallel
ctest --test-dir build --output-on-failure
```

On Windows use `--config Release` for the build and `-C Release` for CTest. For isolated Linux audio integration, install the PipeWire utilities listed above and run:

```bash
dbus-run-session -- python tests/run_private_pipewire.py
```

Standard tests skip opt-in real-audio cases. Mock success and a successful CI build do not establish hardware audio or driver correctness. Windows hardware playback and actual driver installation need target-machine validation.

## Source structure

```text
a2router/              Qt UI, controller, configuration, platform backends
src/                   MultiRoute WASAPI engine, C ABI bridge, device helper
vendor/vbcable/        Original VB-CABLE archive, checksum enforcement and notices
drivers/windows/       VB-CABLE integration documentation
tests/                 Python, C++ and opt-in audio integration tests
tools/windows/         Reproducible application/driver builds and diagnostics
docs/                  Platform setup, architecture and verification scope
.github/workflows/     GitHub Actions builds and checks
CMakeLists.txt         Native C++20 application build
pyproject.toml         Python dependencies and entry point
THIRD_PARTY_NOTICES.md  Upstream attribution and dependency notices
```

## Credits and licensing

- **[vkr-6/MultiRoute](https://github.com/vkr-6/MultiRoute)** — source repository used as the foundation for A2Router's Windows engine.
- **[FulminataXII/MultiRoute](https://github.com/FulminataXII/MultiRoute)** — original upstream audio-routing project. Credit to its authors for the WASAPI engine, ring buffers, drift controllers, telemetry and original frontends.
- **[VB-Audio Software](https://www.vb-cable.com/)** — VB-CABLE virtual audio driver by Vincent Burel / JS-Loezic. The original Pack45 ZIP and vendor license are preserved unchanged. VB-CABLE is donationware; contributions are welcome.
- **OpenAI Codex** — AI coding assistant used to develop the A2Router application additions, Linux backend, Qt interface, configuration handling, Windows integration, driver adaptation, documentation and workflows under the project owner's direction. This development credit does not replace upstream authorship or imply verified correctness.

No standalone license file was present in the imported MultiRoute checkout. A2Router does not assign a new blanket license to that existing engine. VB-CABLE retains its own proprietary donationware license; it is not A2Router-authored code. See [third-party notices](THIRD_PARTY_NOTICES.md) for attribution and component licensing. Original [MultiRoute documentation](docs/upstream-windows.md) is retained.
