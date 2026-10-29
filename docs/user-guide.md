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
affect other applications. VB-CABLE is grouped once and uses A2Router stream gain,
which does not change the vendor endpoint master volume. Its input meter is before
routed gain, so it can still move while routed playback is muted. With no cable
routes, an old DLL, or differing route gains, controls explain their limitation.
Adjust differing gains using Selected route level in Routing.

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
excludes LFE and normalizes for coherent full-scale headroom. Mono downmix also
excludes LFE. Stereo upmix copies fronts, derives centre at 0.5 L + 0.5 R, and uses
attenuated copies for surround pairs; LFE stays silent. This is stereo expansion,
not recovered discrete surround. Conversion uses reported positions, never guessed
indices. The native matrix clamps mixed samples; processed paths are not bit-perfect.
Linux custom matrices remain unavailable.

Calibration is Windows-only and requires the updated native DLL, a physical
microphone and at least two physical outputs. Choose the microphone channel,
checked outputs, reference output, pass count and conservative test level. Keep the
microphone fixed at the listening position, hardware volume safe and other apps
quiet. A confirmation precedes sequential first-channel chirps. Native recording and
playback are separate from GUI rendering; Python analyzes only completed recordings.

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

Settings offers System/White/Dark/Lime/Blue/Violet and density. The new A-squared logo
uses a simple blue routing monogram with a transparent background. Diagnostics contains
backend observations and logs; export prompts for review of IDs/names/library paths.

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
