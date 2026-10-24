A2Router for Linux x86_64

Extract the complete folder and run ./a2router. Python/Qt/NumPy are bundled.
Targets glibc-based Linux distributions compatible with the build runner
(Ubuntu 22.04 or newer); PipeWire, pipewire-pulse and pactl are system dependencies.
A working desktop display/session and Qt platform libraries are required.
Ubuntu/Debian: install pipewire pipewire-pulse pulseaudio-utils libegl1 libopengl0
libxcb-cursor0 libxkbcommon-x11-0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1
libxcb-render-util0 libxcb-xinerama0 using your normal package manager.

The .deb installs the same bundle under /opt/a2router and a desktop launcher.
No driver, permanent application service or audio defaults are installed/changed.
Windows VB-CABLE and WASAPI acoustic calibration are unavailable on Linux.
Linux device routing and virtual sinks use the existing PipeWire backend.
Profiles and UI settings are kept in the user's configuration directory.
See LICENSE, LICENSING.md and THIRD_PARTY_NOTICES.md for component-specific terms.
