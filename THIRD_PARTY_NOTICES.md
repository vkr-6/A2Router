# Third-party acknowledgements

## MultiRoute audio engine

A2Router reuses and extends the Windows WASAPI engine from:

- [vkr-6/MultiRoute](https://github.com/vkr-6/MultiRoute), the source repository used for this project.
- [FulminataXII/MultiRoute](https://github.com/FulminataXII/MultiRoute), the original upstream project.

Credit belongs to those authors for the original audio engine, buffering, drift compensation, telemetry and native frontends. Existing source comments and attribution are retained. No standalone license file was present in the imported MultiRoute checkout; this notice does not assign a new license to that code or establish redistribution rights beyond the upstream terms.

## Microsoft Windows Driver Samples

`drivers/windows/a2router/` derives from Microsoft SimpleAudioSample at commit `bb68ed5e770bce04dc5395ec9258dafab034184d`:

https://github.com/microsoft/Windows-driver-samples/tree/bb68ed5e770bce04dc5395ec9258dafab034184d/audio/simpleaudiosample

Microsoft copyright notices are retained. This driver source is covered by the Microsoft Public License (MS-PL); its complete text is in [LICENSE-Microsoft.txt](drivers/windows/a2router/LICENSE-Microsoft.txt). [UPSTREAM.md](drivers/windows/a2router/UPSTREAM.md) records provenance and [driver documentation](drivers/windows/README.md) describes local modifications. The MS-PL applies to this component; it is not asserted as a license for the whole application.

## Runtime and build dependencies

Python, Qt/PySide6, shiboken6, PyInstaller and other dependencies retain their respective licenses. `tools/windows/collect_licenses.py` collects installed runtime license notices into portable build artifacts. A separately distributed driver package includes its Microsoft source license. Dependency versions are recorded in the portable bundle's `build-info.json`.

## Development credit

The A2Router application additions, platform integration, configuration UI, driver adaptation, documentation and build automation were developed with **OpenAI Codex**, an AI coding assistant, under the project owner's direction. This acknowledgement does not replace upstream authorship or imply that untested code has been validated.
