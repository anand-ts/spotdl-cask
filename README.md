# spotDL Web Downloader

A small desktop/web wrapper around `spotdl`.

## What remains

- `app/` contains the runtime, routes, metadata service, download service, settings, and binary helpers.
- `static/` and `templates/` contain the frontend shell.
- `dev`, `run`, and `setup` are the only shell entrypoints kept.

## Run it

```bash
./dev
```

or

```bash
./run
```

`./setup` installs dependencies into `.venv` with `uv`.

## Notes

- Python stays pinned to `<3.14` because of `spotdl`.
- Spotify links still rely on Spotify credentials that `spotdl` can access.
