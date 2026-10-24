# A2Router workspace guide

## Navigation and profiles

The top strip opens Audio Routing, Mixer, Devices, Virtual Devices, Calibration,
Diagnostics and Settings. Icons sit above the captions. File/Edit/View/Routing/
Devices/Tools/Help menus expose the same real operations and keyboard shortcuts.
No driver is installed when the application starts.

Use New, Open, Save and Save As for version-1 JSON profiles. Open/recent-profile
selection replaces the route set after confirming unsaved changes; invalid JSON
is rejected before changing routes. CLI `load` retains its existing merge behavior.
Unavailable endpoints remain pending and retain their stable device IDs. Profile
switching retains existing virtual devices rather than deleting shared audio
resources; New clears routes and aliases, not installed virtual devices. A `*`
marks changes since the last named-profile save; automatic session persistence
is separate. UI layout and theme preferences use QSettings, not audio-profile JSON.

Shortcuts: Ctrl+N new; Ctrl+O open; Ctrl+S save; Ctrl+Shift+S save as; Ctrl+R/F5
refresh; Ctrl+F input filter; Ctrl+Shift+M emergency stop; F1 guide. Global system
hotkeys and undo/redo are not implemented.

## Routing Configuration

Input/output tables show observed devices, IDs, channels, rates, formats and state.
Select an input and output, check microphone monitoring only when safe, and Add
route. Multiple destination routes provide fan-out; multiple sources use the
OS/native shared-mode mixing path. No endpoint is substituted for a missing ID.

Double-click output volume or mute to edit supported endpoint controls. These
are system endpoint controls and affect other applications using the endpoint.
Changes are confirmed by backend observations. Unsupported measurements show N/A.

Use the table filters, column-header sorting and draggable columns. Right-click
headers to show/hide columns; right-click rows to copy or export CSV. Column widths,
visibility/order, window geometry and splitter positions are remembered.

Select multiple routes for Enable, Disable or Remove, including through the
context menu. These edit desired profile state. Start Routing runs enabled routes;
Stop Routing stops managed transport while retaining enabled/disabled choices.
Polling and reconnect recovery respect the stopped state. Emergency Mute discards
queued UI mutations and requests transport stop without changing system volumes;
it waits behind the currently executing control operation and is not a hardware
panic switch. Review any stop errors. Explicit Start resumes enabled routes.
Closing hides/minimizes the window; File → Exit stops the Windows engine. Linux
server-owned routes can remain running after controller exit, as before.

## Synchronization and delay

Open Audio Routing → Routing Configuration → Synchronization & Delay Compensation.
Choose a route, edit its additional delay and Apply. Discard edit restores the
saved request. Native delay controls currently accept integer milliseconds, not
fractional milliseconds. A stopped route retains the request without starting audio.

Supported live updates adjust the target inside the existing ring-buffer ceiling.
If that cannot work, the source can restart only when the restart checkbox allows
it. Other outputs sharing that capture source can be affected by a restart. The
native clock controller remains automatic; buffer/target, rate correction,
underruns and clipping come from native observations. No editable reference clock,
buffer target, drift tolerance or acoustic measurement is exposed.

Latency values are not acoustic arrival times. If independent measurements show
12/40/75 ms arrivals, manual relative compensation would be +63/+35/+0 ms; A2Router
does not currently measure or automatically apply that example. Calibration is
explicitly deferred to the next upgrade and its page links to manual controls.

## Channel Matrix

Select endpoints in Routing Configuration, then open Channel Matrix. Rows follow
the reported source channels and columns follow destination channels, up to the
backend's supported limits. Enable Custom channel routing for explicit processing.
Double-click a grid cell to connect/disconnect it. Select several cells, set gain
and use Set selected gains or Disconnect selected. The sparse connection list
below remains editable and uses the same draft.

Identity, Stereo swap and normalized Mono sum presets require appropriate actual
channel counts. Mono sum uses 1/N gain per input and duplicates the sum to selected
output channels. No implicit surround downmix preset or guessed layout is used.
Unmapped destination channels are silent. Maps have a 1024-connection limit.

Add route uses the draft for a new route. To edit an existing route, select it in
Routing Configuration, Load selected route, edit, and Apply to selected route.
The confirmation explains the source restart and silent unmapped channels. Invalid
maps are rejected; a rejected backend connection restores the previous map and
reports any recovery failure. Gains outside this editor's −60..+12 dB range,
including phase-inverted gains, cannot be loaded losslessly and are rejected for
editing; their saved route definitions remain intact.

Windows performs real-time processing in C++, including remapping, duplication,
summing and peak clamping. It is not bit-perfect. Linux custom maps remain
unsupported, with an explanatory disabled editor. Advanced Processing describes
implemented matrix processing and links to its controls; EQ, compressors, pan,
exclusive mode and a test-tone generator are absent.

## Mixer, virtual endpoints and diagnostics

Mixer exposes supported endpoint volume/mute and observed Windows peak history.
No RMS or CPU measurements are synthesized. Linux peak graphs remain unavailable.
Devices provides selected endpoint specifications. Virtual Devices retains the
explicit VB-CABLE installation/removal confirmations, supported-format scan,
channel/rate/bit-depth selection and Windows rename. Stop transport before format
changes. Vendor files and authenticity verification remain unchanged. A single
base cable cannot create unlimited independent devices.

A rename reopens the Windows endpoint/property store for verification and retries
briefly for delayed observation. A rejected write does not cause an unnecessary
rollback write. Access-denied writes/commits use the existing explicit elevation
flow in the portable app. Failures include the actual HRESULT; the app does not
claim success without a verified name. Windows target validation remains necessary.

Diagnostics shows backend observations and a bounded timestamped action/error log.
Export prompts for review because device names/IDs and library paths can identify
a system. The JSON export is written atomically on the worker. Clear visible log
only clears the app log. Settings offers System/Light/Dark and two density choices.
Windows Sound and Volume Mixer commands are available only on Windows.
