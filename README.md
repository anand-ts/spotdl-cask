# spotDL Web Downloader

A small desktop/web wrapper around `spotdl`.

## Backend shape

- `app/backend/` contains the new lean backend:
  - `jobs.py` owns queueing, status, cancellation, and reveal tracking
  - `workers.py` owns per-job subprocess monitoring and timeout handling
  - `download_worker.py` runs one `spotdl` job per subprocess
  - `metadata.py` and `metadata_worker.py` handle best-effort metadata lookup
  - `settings.py` and `os.py` handle persisted download folder state and OS integration
- `app/routes.py` and `app/web.py` are thin Flask adapters over that backend.
- `static/` and `templates/` contain the frontend shell.
- `dev`, `run`, and `setup` are the only shell entrypoints kept.

## Setup

```bash
./setup
```

`./setup` runs `uv sync`, and the project is expected to be launched through `uv run`.

## Run it

```bash
./dev
```

or

```bash
./run
```

`./dev` and `./run` both launch through `uv run`, so `uv` owns the environment instead of the scripts hardcoding `.venv/bin/python`.

## Notes

- Python stays pinned to `<3.14` because of `spotdl`.
- Spotify links still rely on Spotify credentials that `spotdl` can access.
- Supported download inputs are currently single Spotify track links and direct media links. Playlist, album, and artist inputs are rejected clearly in v1.
