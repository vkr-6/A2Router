# Linux backend

The backend runs `pactl -f json` for devices, streams and server observations. It uses the stable audio-server names as endpoint identifiers, rather than numeric sink/source indices. Those names can still change if a user changes device profiles or server naming policy; a pending definition is retained rather than redirected to another device. Current format/channel maps describe the active server format, not every format the hardware can support. Missing metadata stays unknown.

`module-null-sink` creates application-selectable virtual sinks. `module-loopback` routes their monitor sources (or physical input sources) to destinations. Several independent modules provide fan-out and server-side mixing. `remix=false` and equal channel position sequences prevent unexpected channel loss/downmixing. No application-level Python sample processing runs. Module options follow the [PipeWire null-sink documentation](https://docs.pipewire.org/page_pulse_module_null_sink.html) and [loopback documentation](https://docs.pipewire.org/page_pulse_module_loopback.html); the local `pactl --help` was also inspected. Actual integration is verified against PipeWire 1.0.5, rather than inferred solely from those documents.

Each module embeds `a2router.owner` and a route/virtual UUID in its properties. Ownership is re-resolved from actual module arguments; persisted numeric IDs are never used to delete anything. Some pactl JSON implementations omit module indices, so a short-table fallback resolves them. Device descriptions use nested PulseAudio property quoting, independently of shell quoting; commands never execute a shell.

Loopback creation verifies both the sink input and source output are attached to the requested endpoint indices. This proves the graph connection, rather than acoustic playback. GUI events use `pactl subscribe`, debounced at 250 ms; polling every three seconds also detects dead subscriptions, server restarts and graph drift. Lost endpoints make enabled routes pending. When safe, subsequent refresh recreates missing virtual sinks and routes, without changing defaults or routing to a replacement endpoint. External graph cycles, acoustic microphone feedback and malicious clients spoofing owner properties cannot be automatically resolved; microphone monitoring requires explicit acknowledgment.

Use `pactl info`, `pactl list short sinks`, `pactl list short sources`, `pactl list short modules`, `pactl -f json list sink-inputs`, and `pactl -f json list source-outputs` to inspect routing independently. Use the virtual sink's monitor as source. Normal desktop operations require no administrator privileges.

The private integration harness uses a temporary runtime directory and `PULSE_SERVER` socket. It can use installed packages, or Ubuntu packages extracted under ignored `build/pipewire-root/usr`. For this session the missing packages were downloaded with `apt-get download` and extracted with `dpkg-deb -x`, avoiding system service installation. Runtime test dependencies include PipeWire's packaged shared libraries, WirePlumber, D-Bus and PulseAudio utilities. The harness intentionally does not provide realtime scheduling privileges; RTKit / hardware-monitor warnings in this headless WSL environment do not constitute hardware verification.

```bash
# On a machine with the tools installed:
dbus-run-session -- .venv/bin/python tests/run_private_pipewire.py
# Alternatively, explicitly test your chosen server (no physical audio destinations):
A2ROUTER_INTEGRATION=1 A2ROUTER_PCM_TEST=1 .venv/bin/python -m pytest tests/test_integration.py -q
```

The daemon restart test is enabled only by the private harness. Integration sinks are silent software destinations and are tagged with a random test owner. Tests clean only their resources; private daemon processes are terminated even after failures. No physical speaker or microphone path was tested in this session.

### Older PipeWire versions

PipeWire 0.3.48 uses a legacy module-argument parser. A2Router preserves virtual
sink names using a compatible quoting path. Names containing both single and
double quotes, or backslashes, cannot be represented faithfully on that version
and are rejected before creating a resource. Use a simpler name or upgrade
PipeWire. Ownership verification and cleanup still apply.
