# Windows virtual audio: VB-CABLE

The former custom WDK/SimpleAudioSample driver, native root-device manager and unsigned-driver build have been removed. A2Router uses the supplied, original **VBCABLE_Driver_Pack45.zip** by VB-Audio Software.

## Package and attribution

- Archive: `vendor/vbcable/VBCABLE_Driver_Pack45.zip` (unchanged).
- SHA-256: `b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb`.
- Official origin: https://www.vb-cable.com/
- Donationware: donations and license purchases are welcome at https://vb-audio.com/Services/licensing.htm.
- Original end-user license is retained inside the ZIP as `readme.txt` and displayed by A2Router setup. See `vendor/vbcable/NOTICE.txt` for distribution conditions, including professional deployments. No A+B/C+D package is included.

## Build and installation

1. Build the normal native WASAPI bridge and portable Python/Qt app using `tools/windows/build-portable.ps1`. No WDK is needed.
2. That script verifies the archive hash and extracts all vendor files without modifying them into `dist/windows-x64/vendor/vb-cable`.
3. Run `tools/windows/build-setup.ps1` with Inno Setup 6.3+ installed. It checks the vendor installer signature and creates `dist/setup/A2Router-Setup-x64.exe`.
4. Run setup on the target Windows x64 machine. Its checked-by-default VB-CABLE task runs the original installer if the base cable is absent, with administrator approval. Existing healthy installations are left untouched.
5. New driver installation needs a restart. Problems are logged to `%TEMP%\A2Router-VBCABLE-install.log`; failed driver installation is reported as a failure, not assumed successful from a vendor exit code. Neither certificate stores nor boot/security policy are changed.

The GitHub workflow remains manual-only. Its `build_setup` input now builds the complete installer instead of an unsigned custom driver. Application uninstallation offers shared-driver removal, with a default based on the recorded installation owner. Pre-existing drivers are never removed silently. Use `/REMOVEVBCABLE=1` to request driver removal during silent uninstall. Failure keeps A2Router/vendor files available for repair. Windows may automatically choose new defaults when installing a driver; review Sound settings afterward. A2Router itself does not select default speakers/microphones.

## Routing and limitations

The base package provides one shared cable, with playback endpoints **CABLE Input** / **CABLE In 16 Ch** and recording endpoint **CABLE Output**. These playback alternatives are not independent named cables. Send source applications to CABLE Input, then select CABLE Output in A2Router as a route source. The native bridge identifies the vendor PnP service rather than inventing endpoints from display names. Reported current formats/layouts come from Windows. VB-CABLE's own control panel manages its internal format/latency options.

The recording endpoint is captured directly with WASAPI; real output-monitor sources remain WASAPI loopbacks. Shared-cable feedback groups prevent routing a cable's recording/monitor stream back to either of its playback endpoints. Independent source sessions and physical-output fan-out still use the preserved MultiRoute engine.

No driver installation is performed during builds/tests or on ordinary application launch. The setup and physical signal paths must be validated on a target machine; package signature/ZIP integrity checks are not audio playback verification.
