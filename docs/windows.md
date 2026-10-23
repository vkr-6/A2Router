# Windows backend

A2Router preserves MultiRoute's WASAPI engine, native SPSC buffers, per-output drift controllers and telemetry. Python controls native source sessions through a C ABI; audio samples never pass through Python. Inputs and output loopbacks are enumerated with reported active formats. Windows shared-mode mixing/rate conversion can alter samples; bit-perfect transport and acoustic alignment are unverified.

## VB-CABLE

Windows virtual audio uses the original VB-Audio base cable package. No custom driver or root-device-creation code remains. See [VB-CABLE setup](../drivers/windows/README.md) for archive provenance, licensing, automatic setup installation, restart and failure behavior. The GUI shows actual cable endpoints and a vendor installer shortcut when its payload is available. It does not pretend this package can create multiple named cables or remove a shared driver automatically.

Select CABLE Input in the source application's output settings, then route CABLE Output through A2Router. Native discovery tags the common PnP service; feedback protection treats all playback alternatives on the same cable as one logical endpoint. The recording side uses real input capture, not a fabricated monitor.

## Synchronization

The Synchronization page retains per-route edits until Apply or Discard, including through periodic refresh and focus changes. Supported live changes call `AudioEngine::setDeviceDelay` through `ar_source_set_delay`; this does not restart the capture source. The engine validates live buffer limits and adjustment-in-flight states. On rejection, the current setting remains unchanged. A source restart fallback is used only when explicitly allowed; disabled-route settings are saved for the next start. The route-delay cache is updated after successful live requests so polling does not restart the session.

Readable telemetry reports buffer fill/target in milliseconds using native block alignment/sample rate, applied rate correction and underruns. Pending, buffering and adjusting states are distinct. Clock drift compensation remains automatic. A fixed delay does not synchronize independent hardware clocks or establish measured acoustic alignment.

## UI refresh and lifecycle

Discovery/polling runs in the serialized backend worker. Device, route and synchronization rows are updated in place by stable ID; unchanged snapshots do not clear widgets or reset scroll/selection. Polling does not disable buttons or flash a status message. User actions arriving during a poll are queued. Backend faults remain visible.

Hiding the window keeps Windows routing alive. Exiting joins the controller and stops its native audio engines. Console invocations cannot sustain audio after their process exits. System defaults and unrelated routes are not explicitly changed by A2Router.

## Build and checks

Build native targets with CMake/MSVC, then use `tools/windows/build-portable.ps1`. The optional setup EXE is compiled with `tools/windows/build-setup.ps1` and Inno Setup 6.3+. GitHub Actions remain manual-only and never install an audio driver on the runner. Headless packaged checks use a labelled mock backend; the actual DLL ABI is separately loaded and checked. Earlier Windows build/discovery checks predate the VB-CABLE and UI revisions; actual installation/playback remain unverified for this revision.
