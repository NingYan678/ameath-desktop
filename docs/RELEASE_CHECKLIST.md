# Ameath release checklist

1. Run `python -m compileall -q src tests packaging hermes_platform`, Ruff, pytest, and `pip check` on Windows Python 3.12.
2. Check out the pinned Hermes baseline in a clean temporary clone; never modify a user's Hermes checkout.
3. Build the offline installer and verify the exact versioned `.exe`, `.sha256`, asset manifest, runtime metadata, and staging cleanup.
4. If signing secrets are available, sign `Ameath.exe` and the installer with SHA-256 and a trusted timestamp. Otherwise label the release unsigned.
5. Test clean install, upgrade, uninstall data retention, Hermes update isolation, proactive replies, sleep/wake, reduced motion, and application update verification.
6. Create an annotated tag and draft GitHub Release; re-download the assets and compare their SHA-256 before publishing.
