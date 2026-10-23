# Third-party acknowledgements

## MultiRoute audio engine

A2Router reuses and extends the Windows WASAPI engine from:

- [vkr-6/MultiRoute](https://github.com/vkr-6/MultiRoute), the source repository used for this project.
- [FulminataXII/MultiRoute](https://github.com/FulminataXII/MultiRoute), the original upstream project.

Credit belongs to those authors for the original audio engine, buffering, drift compensation, telemetry and native frontends. Existing source comments and attribution are retained. No standalone license file was present in the imported MultiRoute checkout; this notice does not assign a new license to that code or establish redistribution rights beyond the upstream terms.

## VB-CABLE by VB-Audio Software

A2Router bundles the original, unchanged `VBCABLE_Driver_Pack45.zip` supplied by the project owner. VB-CABLE is programmed by V. Burel / JS-Loezic, copyright VB-Audio / Vincent Burel, 2010–2024, all rights reserved. It is proprietary donationware, not an A2Router-authored or open-source driver.

Origin: https://www.vb-cable.com/. Donations and license purchases are welcome: https://vb-audio.com/Services/licensing.htm. See `vendor/vbcable/NOTICE.txt` and the original `readme.txt` inside the ZIP. The published bundling permission applies when end users can identify VB-CABLE and donate/pay; professional contexts may require separate licenses. A+B and C+D are not bundled. Vendor files/signatures are not modified; no certificates or boot policy are changed by A2Router's installation code.

The prior Microsoft-derived custom driver has been removed and is no longer included in source or artifacts.

## Runtime and build dependencies

Python, Qt/PySide6, shiboken6, PyInstaller and other dependencies retain their respective licenses. `tools/windows/collect_licenses.py` collects installed runtime license notices into portable build artifacts. The bundled VB-CABLE payload retains its original vendor license and notices. Dependency versions are recorded in the portable bundle's `build-info.json`.

## Development credit

The A2Router application additions, platform integration, configuration UI, driver adaptation, documentation and build automation were developed with **OpenAI Codex**, an AI coding assistant, under the project owner's direction. This acknowledgement does not replace upstream authorship or imply that untested code has been validated.
