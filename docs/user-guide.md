# A2Router guide

Audio Routing contains only configured routes, endpoint selectors, optional Channel
Matrix and collapsed Synchronization & delay. Select a source/destination and Add
route. Add destination routes for fan-out; multiple sources use shared-mode mixing.
Microphone monitoring requires explicit feedback-risk confirmation. Select routes to
enable, disable or remove them; supported Windows streams also have a selected-route
level/mute control. Stop Routing preserves enabled choices; Start resumes enabled
routes. Emergency Mute clears queued mutations and stops managed transport; it also
cancels calibration without resuming playback. Ordinary stop remains serialized and
can wait behind an active control operation.

Mixer uses narrow observed peak meters, not history graphs. Physical endpoint levels
affect other applications. VB-CABLE is grouped once; its default control scope is
Windows-linked managed playback. Route trim is a separate gain stage.
The cable input meter is before routed gain, so it can still move while routed
playback is muted. Adjust differing route gains using Selected route level in Routing.

Devices combines input/output inventory and Configure. Physical endpoints and cable
pins can be selected for exact format scanning where the backend supports it. Only
accepted formats are offered; stop dependent routes before applying changes. Keep
Windows/vendor endpoint names. The base cable has several pins sharing one cable;
it does not provide independent virtual cables. Install/remove driver actions remain
explicit and may request UAC. Review restart requirements; no reboot is forced.

Profiles are only in File: New, Open, Save, Save As and Recent profiles. Invalid JSON
is rejected before replacing routes. Missing endpoints retain desired definitions.
Virtual devices omitted from another profile are retained for ownership safety.
Old version-1 profiles remain readable; optional volume/muted/calibration fields
extend that schema. Audio profiles do not include UI themes/layout preferences.

Channel Matrix has dynamic source/destination axes. Double-click connections or edit
the sparse list. Select cells for bulk gain/disconnect. Presets explicitly load a
draft; Add route or Apply to selected route performs the operation. Existing-route
changes warn about a source restart and attempt rollback on backend failure.

Downmix to stereo uses front channels plus attenuated centre/surround contributions,
excludes LFE and keeps front channels at unity by default. Choose −3 dB headroom
or Normalize peaks for more conservative summing. Normalization is quieter by
design. Reload and apply a preset to change an existing matrix. Mono downmix also
excludes LFE. Stereo upmix copies fronts, derives centre at 0.5 L + 0.5 R, and uses
attenuated copies for surround pairs; LFE stays silent. This is stereo expansion,
not recovered discrete surround. Conversion uses reported positions, never guessed
indices. The native matrix clamps mixed samples; processed paths are not bit-perfect.
On PipeWire, unity-only remapping and duplication use native port links; DSP
conversion presets are unavailable there.

Calibration is Windows-only and requires the updated native DLL, a physical
microphone and at least two physical outputs. Choose the microphone channel,
checked outputs, reference output, pass count and conservative test level. Keep the
microphone fixed at the listening position, hardware volume safe and other apps
quiet. A confirmation precedes sequential first-channel chirps. Native recording and
playback are separate from GUI rendering; Python analyzes only completed recordings.

Devices → Inputs contains **Recording access**. Both switches start off:
**Allow recording inputs for this session** permits virtual cable recording, while
**Enable physical microphones for this session** separately permits microphones.
Microphone routing, physical-input format scanning and calibration require both.
Turning physical microphones off cancels calibration and stops microphone routes;
virtual cable playback can continue. Turning all recording off stops all capture,
including cable recording. Neither permission is saved in profiles. Input rows show
recording access separately from endpoint availability.

Windows labels virtual-cable recording as microphone use too. Its recording
indicator can remain on during a cable route without physical microphone capture.
No app can truthfully hide this activity while continuing to record the cable.
Native discovery uses read-only input properties and does not activate input audio
clients, volume, topology or peak interfaces. Input endpoint sliders/meters are
unavailable instead of waking microphones. Rebuild the native DLL for these changes.
Windows microphone permissions must also allow the requested input.

Measurement stops managed routes temporarily and restores their previous enabled
states after completion, cancellation or failure. Cancel stops the current test.
Emergency Mute/Exit suppress restoration of playback. Invalid request preflight does
not stop routes. Mic permission, format, timestamp, discontinuity, underrun, clipping,
noise, ambiguous reflections and unstable-pass errors are reported.

Results are arrival offsets relative to the selected reference and compensation
relative to the slowest measured output. Earlier devices are delayed; no device is
made to play earlier than physically possible. Confidence is a heuristic based on
normalized correlation and repeated-pass spread, not a statistical precision claim.
The capture reference uses QPC timestamps and a software-render-start epoch; startup
jitter, room propagation, reflections and hardware/transport delay cannot be fully
separated. A strongest matched arrival may not equal the earliest room reflection.

Review/edit compensation, then Apply reviewed delays. All configured routes to the
measured outputs receive those requests. Native requests round to integer ms; large
changes need explicit source-restart permission. A partial failure attempts rollback
and reports failed recovery. Revert edits restores recommendations in the table;
it does not undo already applied engine delays. File → Save stores calibration
metadata and desired route delays; Export measurement writes reviewed JSON metadata.
The full Windows acoustic path still requires target-machine build/hardware testing.

Settings → Appearance is the only theme selector. Orange uses neutral charcoal
panels, darker tables and subtle orange selections/underlines, plus
System/White/Dark/Lime/Blue/Violet alternatives. Original outline navigation icons
use neutral text colour when idle and the theme accent when active. Settings also
provides density controls. This branding update switches existing installations to Orange
once; subsequent theme choices are preserved. Application and packaging icons use
only the orbital-A mark from the supplied PNG, centered on a square transparent
canvas. README branding retains the full wordmark. Windows ICO sizes preserve the
mark’s proportions; rebuilt packages update the application and shortcut icons.
Windows can retain cached icons for older shortcuts. The Diagnostics page
and GUI export/log controls have been removed. Backend errors remain visible in
the status bar, and existing command-line diagnostics are still available.

Theme updates apply to menus, dropdowns, dialogs and navigation icons together.
Older releases migrate to the corrected Orange default once; later theme choices
remain saved. Popups close when the window hides/minimizes, the workspace changes,
or the application loses focus.

On Linux, **Idle (suspended)** means the audio server has paused an unused endpoint,
not that virtual-device creation failed. It normally wakes when an application
plays into it or a route uses it. Run A2Router as your desktop user; sudo is not
needed for ordinary virtual sinks/routes. If audio stays silent while playing,
check the selected application sink, route status and mute controls. Device
properties and command-line output retain the server's raw state.

Shortcuts: Ctrl+N/Open Ctrl+O/Save Ctrl+S/Save As Ctrl+Shift+S, refresh Ctrl+R/F5,
filter Ctrl+F, emergency Ctrl+Shift+M, help F1. Closing hides/minimizes; File → Exit
stops Windows native processing. Linux server-owned routes can remain running.

Windows distribution includes a portable ZIP and optional setup EXE. Setup checkboxes
control shortcuts, launch and optional shared-driver installation; driver installation
and removal are unchecked by default. Uninstall preserves profiles and the shared
driver unless explicitly selected. Linux has separate tar.gz and .deb packages;
PipeWire and desktop system libraries are dependencies, not bundled audio services.

### Channel formats and calibration troubleshooting

Select the source and output directly in Channel Matrix. Its rows and columns
follow the active endpoint formats. Windows may save a device format before the
active audio engine adopts it; close applications using that endpoint and refresh
if the active channel count has not changed. A VB-CABLE playback endpoint and
its recording endpoint have separate active formats: inspect both rather than
assuming a playback-format change also reconfigures capture.

Quiet ambient microphone samples are allowed before a calibration chirp. If the
entire recording remains silent, check the selected physical microphone channel,
mute, Windows microphone permission and whether the chosen speaker is audible
at the microphone. A silent digital stream cannot provide an acoustic delay.

### Input-monitoring confirmation and capture startup

Adding a microphone/input route to a physical output now asks for explicit
confirmation if monitoring has not already been allowed. Declining leaves the
route uncreated. Approval is stored on that route; direct feedback loops remain
blocked by the backend.

Windows acoustic calibration discards the initial 250 ms of capture packets to
allow microphone startup to settle, before the test chirp begins at 450 ms. The
recording anchor remains a real microphone timestamp. Invalid timestamps or lost
packets during the subsequent measurement still reject the pass. If this persists,
close other microphone applications, disable microphone enhancements, and try a
wired/USB microphone, especially when measuring Bluetooth playback.

### Cable control scope

Mixer → Cable volume defaults to **Windows-linked managed playback**. Its slider
writes the real Windows cable playback endpoint; Windows changes are read back and
applied to all A2Router cable routes using native stream gain. Per-route trims and
mute remain independent. No routes restart for gain changes. Synchronization
polling continues while the Mixer page is hidden. Unsupported or unverified stream
updates report an error; an unverified linked update attempts to stop its source.

The vendor **Windows Volume Control** option must stay **OFF** in linked mode;
otherwise both the driver and A2Router apply master gain. If it is ON, select
**Windows volume (driver-managed)**, which removes the additional master factor.
**Route trim** offers the previous independent app-only controls. Preferences retain
the selected mode. The driver option is never changed automatically. Linked gain
only affects A2Router-managed streams; other recording applications require vendor
volume support. Control the same cable playback endpoint in Windows Sound. Default
endpoint status and the reported cable device description select the main pin;
endpoint names are never used as route identities.

### Routing software and editing channels while playing

In Audio Routing choose Sources → Applications after starting the application's
sound. Add a route for each additional destination. The source label says
application copy because original playback stays active. Choose additional
outputs to avoid hearing the original and a duplicate together. Saved rules use
executable identity rather than a process-list position. Closed apps leave pending
routes; refresh safely reconnects them when the app returns.

Windows requires build 20348+ and the rebuilt native bridge. It captures a selected
process tree as explicit stereo PCM; independent instances and protected content
have limitations. Linux requires pw-dump/pw-link in a native PipeWire session and
preserves original application links. Its native channel links provide unity gain,
so conversion/DSP gain controls are disabled. Additional delay is unavailable on
Linux application/channel links and is never silently ignored.

Select a route and click Channels…; edit and Apply to selected route. Compatible Windows float paths and existing custom maps update live.
The first edit is live when float formats/channel counts match. Other formats
require a source restart to negotiate custom processing. Other mapped outputs keep running
during subsequent edits. Device channel-count changes still need stopping the
routes that use that device. PipeWire edits only the selected route's owned links.


### Channel matrix on PulseAudio

The status bar identifies the active server. A classic PulseAudio server uses a
remap-sink/loopback fallback; native PipeWire uses port links. Both support unity
channel remapping/duplication. Weighted gains/conversion presets require a native
processing backend and stay disabled where unavailable.

1. Choose the source and destination on Routes and add the route.
2. Open Channel Matrix. The matrix uses the endpoints' actual reported channels.
3. Click Load preset for Identity, or double-click cells to connect/disconnect.
4. Click Apply to selected route and confirm. A unique route matching the chosen
   source/destination is found automatically if no route row is selected.

On PulseAudio, applying restarts only this route. Summing can clip, unmapped
outputs are silent, and the fallback allows at most 64 connections. Internal
helper sinks/monitors are hidden from A2Router's device selectors. If a server
rejects module loading, the route reports the error and partial resources are
cleaned up. No sudo or Windows installation is needed.
