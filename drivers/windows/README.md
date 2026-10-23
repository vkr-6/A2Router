# VB-CABLE integration

A2Router includes the unchanged VB-Audio base package `vendor/vbcable/VBCABLE_Driver_Pack45.zip`.
SHA-256: `b950e39f01af1d04ea623c8f6d8eb9b6ea5c477c637295fabf20631c85116bfb`.

Build the portable app with `tools/windows/build-portable.ps1` or the manual GitHub workflow. `prepare_vbcable.py` verifies the hash and extracts all original vendor files. No WDK, custom driver or application setup EXE is used.

The GUI's **Virtual devices → Create output** requests UAC only when the cable is absent. `windows_vbcable.py` waits on an elevated `install-vbcable.ps1`, which validates the vendor signature and executes the original installer. PnP status is checked independently of its exit code. The GUI/backend then refresh active WASAPI endpoints. Immediately ready devices can be used; reported restart requirements remain visible. Installing on launch or profile restoration is prohibited by design.

One shared cable is available; separate A/B/C/D drivers are not included. Virtual devices scans exact driver formats and exposes channel/bit-depth/sample-rate configuration plus a real Windows endpoint rename action. The private format-policy boundary verifies changes and rolls back failures; Windows Sound remains available. Configure recording and playback endpoints separately for multichannel routing. The native bridge identifies actual cable endpoints through the `VBAudioVACMME` PnP service and blocks cable feedback, including alternative playback pins.

**Remove driver…** requires explicit confirmation and removal of dependent routes. It affects all apps using the shared cable. Vendor uninstall is verified through PnP and may request a restart. Deleting A2Router's portable folder leaves the driver installed unless you remove it first. No certificate or security-policy changes are made; Windows may select different default sound devices during driver installation.

VB-CABLE is donationware by [VB-Audio Software](https://www.vb-cable.com/). The original copyright, files and `readme.txt` license remain unchanged. [Donations, licensing and bundling terms](https://vb-audio.com/Services/licensing.htm); professional deployments may require separate licensing. See `vendor/vbcable/NOTICE.txt`.

Driver operations and native audio transport require target-machine verification. ZIP integrity, signatures and simulated installer tests do not establish playback correctness.
