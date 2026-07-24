"""PyInstaller entry point that preserves the ``digital_pet`` package context."""

from digital_pet.main import run


if __name__ == "__main__":
    raise SystemExit(run())
