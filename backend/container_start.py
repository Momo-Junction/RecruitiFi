"""Container-only preflight; run the existing backend.main:app with one worker."""
import os
from pathlib import Path


def validate_runtime():
    if os.geteuid() == 0:
        raise RuntimeError("Run with a platform-assigned non-root UID; root runtime is not supported.")
    if os.environ.get("TALENTMATCH_HOSTED_DEMO") == "1":
        if not os.environ.get("TALENTMATCH_DEMO_PASSWORD", "").strip():
            raise RuntimeError("TALENTMATCH_DEMO_PASSWORD is required for hosted demo mode.")
        raise RuntimeError(
            "Hosted demo authentication is not implemented in this checkout. "
            "Deployment is blocked; do not expose this unauthenticated application."
        )
    database = Path(os.environ.get("TALENTMATCH_DB", ""))
    if not database.is_absolute() or database.parent != Path("/var/data"):
        raise RuntimeError("Container TALENTMATCH_DB must be an absolute file path directly in /var/data.")
    # SQLite must also create journal/WAL/SHM files in the parent directory.
    import tempfile
    with tempfile.TemporaryFile(dir=database.parent):
        pass
    # SQLite may otherwise create a 0644 database even with a permissive umask.
    # Exclusively precreate a group-writable empty file; never truncate existing data.
    try:
        fd = os.open(database, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o660)
    except FileExistsError:
        if not os.access(database, os.W_OK):
            raise RuntimeError("Existing SQLite file is not writable by the assigned UID/storage group.")
    else:
        os.close(fd)
    if not (Path(__file__).resolve().parent.parent / "frontend/dist/index.html").is_file():
        raise RuntimeError("Built frontend assets are missing from the image.")


def main():
    # Preserve group write access when a replacement Pod receives a different UID.
    os.umask(0o007)
    validate_runtime()
    import uvicorn
    uvicorn.run(
        "backend.main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8080")),
        workers=1, timeout_graceful_shutdown=25,
    )


if __name__ == "__main__":
    main()
