# Windows audit corrections — 3 November 2026

The supplied 2 November Windows audit describes external tests of commit
`4b087786ecdc28682e422f2bc77b0c4ba39b4136` and previously supplied binaries.
Its hardware results were not repeated in this Linux development session.

Applied corrections:

- Ctrl+F reveals Devices → Inputs before focusing the filter (B1).
- Device properties follows the active Inputs/Outputs tab and refuses stale
  selections on Configure (B2). Status counts now say active sources/outputs (U1).
- Physical microphone routes and calibration require explicit session-only
  permission. Revocation stops physical input sessions and cancels measurement.
  A queued earlier enable cannot override a later revocation.
- Native input discovery reads configured format properties without activating
  an input audio client. Input peak meters are not opened. Rebuilding the native
  DLL is necessary; Windows privacy-indicator behavior still needs hardware tests.
- VB-CABLE defaults to Windows playback-endpoint volume, with separate route trim
  and visible guidance for the vendor Windows Volume Control setting. No driver
  options, endpoint defaults or Windows permissions are changed automatically.
- The application mark is centered without distortion on a transparent square.
  The same image supplies app/tray icons, generated multi-size ICOs and packaging.
- About and package metadata include source/build identity. Calibration requirements
  and absent-driver panel controls have explanatory text.

Local verification: `QT_QPA_PLATFORM=offscreen ... python3 -m pytest -q`:
**203 passed, 22 skipped**. Ruff check/format and `git diff --check` passed.
Linux CMake Release build and CTest: **1/1 passed** (portable native core).
Generated ICO payloads decoded at 16, 24, 32, 48, 64, 128 and 256 pixels.
Python Windows-backend tests use explicit simulated bridges, not real devices.

Not verified here: compilation of the modified Windows DLL, Windows acoustic
calibration, audible cable/system volume behavior, taskbar icon caching, driver
install/removal, release signing, multi-device PCM fidelity or long-duration drift.
No Windows software was installed and no Windows settings were changed. The
reported microphone timing failure remains subject to hardware investigation;
validation was not weakened to accept unreliable recordings. Use the manual Windows
build workflow and repeat the audit against newly identified artifacts.

## Recording and cable-volume follow-up

Devices → Inputs now exposes two switches, both off at startup: all recording
access (including virtual cables) and physical microphone access. Enabling cable
recording alone cannot restore physical microphone routes. Turning physical
microphones off leaves cable routes running; turning all recording off stops both.
The native capture-access extension also rejects recording starts and input format
probes while closed and removes input sessions on revocation. Input discovery no
longer activates endpoint volume or topology interfaces either.

The user's clarification was that Windows shows recording activity **only while a
VB-CABLE route plays**. That is expected virtual-input capture activity, not evidence
that a physical microphone is open. The Windows indicator cannot be hidden while
recording the cable. The new controls make these permissions explicit.

Windows-linked managed playback now writes the real cable playback endpoint's
volume/mute and applies its observed master value to native A2Router route trims.
System changes are followed even outside Mixer. Device descriptions and default
status choose the main playback pin rather than arbitrary enumeration order.
Driver-managed mode removes the additional master factor; it is the mode to use
when the vendor Windows Volume Control option is enabled. No driver setting is
changed automatically. Other recording applications still require vendor support.

Follow-up verification: **210 passed, 23 skipped**, Ruff check/format passed,
portable native CTest **1/1 passed**. Added tests cover independent microphone/cable
permissions, native guard calls through simulated bridges, app/system cable gain
and mute synchronization, fan-out, mode changes, failed gain updates, and background
polling from Settings. An opt-in real Windows DLL guard test was added and skipped
on Linux. The modified Windows DLL and audible behavior remain unverified locally;
no Windows installations or settings changes were performed.
