"""Entry script used by both native Windows PyInstaller bundles."""

from a2router.portable import main

if __name__ == "__main__":
    raise SystemExit(main())
