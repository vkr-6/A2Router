# GitHub project description

> Windows WASAPI and Linux PipeWire audio routing with a compact Qt interface, multi-output playback, channel conversion, profiles and Windows microphone calibration.

A2Router (Advanced Audio Router) combines a native C++20 Windows engine and Linux
PipeWire routing with a portable PySide6 desktop interface. It manages concurrent
routes, virtual-cable integration, explicit channel conversion, stream controls,
supported software delays and review-first microphone-assisted calibration. Manual
GitHub Actions build Windows portable/setup and separate Linux tar.gz/.deb packages.
Native Windows calibration and this revision's Windows binaries still need target
build and hardware verification. Original additions are MIT licensed with explicit
upstream/vendor exclusions; the complete bundled dependency tree is not all MIT.
