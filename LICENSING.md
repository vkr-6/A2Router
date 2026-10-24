# License scope

The root MIT license applies to the original A2Router contributions: the Python
package, application assets, tests, build automation, new documentation, and the
native integration files `src/PythonBridge.cpp`, `src/WindowsEndpointControl.h`,
`src/ChannelMatrix.h`, `src/EndpointRename.h`, `src/CalibrationSignal.h`
and `src/WindowsCalibration.h`.

The following are excluded from that license grant:

- Other files under `src/` and `docs/upstream-windows.md`: reused MultiRoute
  code/documentation. The imported snapshot did not contain an upstream license.
  A2Router cannot grant rights to someone else's code. Obtain permission or an
  explicit license from the upstream copyright holders before redistributing
  those components under open-source terms.
- `vendor/vbcable/`: original VB-Audio proprietary donationware package and its
  accompanying notices. It is not MIT licensed. Follow the vendor's terms.
- Third-party runtime/build dependencies: retain their own licenses. Portable
  builds collect runtime license notices alongside the executable.

Modifications to imported files do not relicense the underlying work. This is
an MIT-licensed application layer with separately governed dependencies, not a
claim that every file or the entire Windows binary is MIT licensed.

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for credits and source links.
