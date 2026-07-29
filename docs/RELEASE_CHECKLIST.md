# Ameath release checklist

## Before building

- Confirm the Ameath worktree is clean and `VERSION` contains the intended
  release.
- Use a clean Hermes checkout at the commit declared by
  `packaging/build_release.py`; do not build from a dirty personal Hermes tree.
- Run Ruff, compileall, `pip check`, and the full pytest suite.

## Build

```powershell
python .\packaging\build_release.py --hermes-source 'C:\path\to\clean\hermes-agent'
```

The script uses a temporary staging directory and removes it after success or
failure. It produces `dist/Ameath-<version>-offline-setup.exe`.

## Verify

- Check the installer filename, embedded application version, and SHA-256.
- Install into an isolated test data directory and exercise startup, tray,
  chat, active interactions, Hermes connection, update checks, and uninstall.
- Test an in-place upgrade while retaining user settings and credentials.
- Record the installer checksum in `BACKUP_MANIFEST.md` only after the smoke
  test passes.
