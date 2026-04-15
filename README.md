# spotDL Web Downloader

<p align="center">
   <img src="public/spotdl_cask_new.gif?v=1" alt="spotDL Web Downloader demo" width="640" />
</p>

## Project Summary

spotDL Web Downloader transforms the command-line [spotdl](https://github.com/spotDL/spotify-downloader) experience into a user-friendly web application. Simply paste Spotify or YouTube links, configure your download preferences, and let the app handle the rest with real-time progress updates and batch processing capabilities.

## Key Features

- **Drag & Drop Support** - Drop links directly onto the interface
- **Paste Detection** - Automatically detects links from clipboard (Ctrl+V / ⌘V)
- **Batch Processing** - Add multiple tracks and download them all at once
- **Audio Quality Control** - Choose from 128k to 320k bitrates or original quality
- **Multiple Formats** - MP3, FLAC, M4A, OPUS, OGG, WAV support
- **Custom Naming** - Flexible filename templates (Artist-Title, Title-Artist, etc.)

## Tech Stack

### **Backend**
- **Flask**
- **pywebview**
- **spotDL** (`spotdl>=4.0.0`)
- **RESTful API**
- **Server-Sent Events (SSE)**

### **Frontend**
- **JavaScript**
- **HTML5**
- **CSS3**
- **SVG**

## Usage

### **Getting Started**

1. **Clone the repository**
   (Repository slug remains `spotdl-cask`; the product name is now **spotDL Web Downloader**.)
   ```bash
   git clone https://github.com/yourusername/spotdl-cask.git
   cd spotdl-cask
   ```

2. **Start dev mode**
   ```bash
   ./dev
   ```
   On the first run, this bootstraps `.venv` automatically and streams all logs directly in the terminal.

3. **Run the desktop app**
   ```bash
   ./run
   ```
   This opens the desktop app window via `pywebview`.

4. **Optional one-time setup**
   ```bash
   ./setup
   ```
   You can run this manually if you want to install dependencies before the first app launch.

5. **Run the test suite**
   ```bash
   ./test
   ```
   This is the canonical test command and runs the full `unittest` suite through `uv`.

6. **Run linting and type checks**
   ```bash
   ./lint
   ./typecheck
   ```
   `./lint` runs Ruff, formatting checks, `ty`, shell-script syntax checks, and frontend JS syntax checks. It will bootstrap the dev tools if they are missing. `./lint-fix` applies Ruff autofixes and formatting.

7. **Open your browser for development mode**
   - Navigate to `http://127.0.0.1:5001`

### **Rules of Thumb**

- Do **not** activate `.venv` manually.
- Do **not** use `npm` unless you intentionally want the compatibility wrapper.
- If port `5001` is busy, run `SPOTDL_PORT=5002 ./dev`.

## Project Layout

- `app/` contains the Flask runtime, routes, diagnostics, binary discovery, and settings primitives.
- `app/services/` contains the Spotify metadata/download-input services and the download orchestration services.
- `static/js/modules/` contains the frontend modules for API calls, state, row rendering, downloads, selection, and settings UI.
- `static/css/sections/` contains the split stylesheet sections that are imported by `static/css/style.css`.

## Build a macOS App

This repo already runs as a desktop app through `pywebview`. To export it as a native macOS `.app` bundle:

1. **Install the dev build tools**
   ```bash
   ./setup --group dev
   ```

2. **Build the application bundle**
   ```bash
   ./build-macos-app.sh
   ```
   If `ffmpeg` and `ffprobe` are installed on the build machine, the script bundles them into the app automatically. The build now also stamps the bundle metadata, applies the custom app icon, and verifies the finished `.app` before returning success.

3. **Open the generated app**
   ```bash
   open "dist/spotDL Web Downloader.app"
   ```

The bundle is created at `dist/spotDL Web Downloader.app`.

4. **Optional: build a DMG**
   ```bash
   ./build-macos-dmg.sh
   ```
   By default this creates `~/Downloads/spotDL Web Downloader 0.1.0.dmg`.

## Packaging Notes

- The app now resolves Flask `templates/` and `static/` correctly in both source and bundled builds.
- Download jobs use the same executable in bundled mode, so the exported app does not rely on a separate `spotdl` command being installed on your `PATH`.
- The exported macOS app now looks for `ffmpeg` inside the app bundle first, then in common macOS locations like `/opt/homebrew/bin` and `/usr/local/bin`.
- To sign exported builds, set `MACOS_CODESIGN_IDENTITY` before running `./build-macos-app.sh` or `./build-macos-dmg.sh`. If you need custom entitlements for the app bundle, also set `MACOS_ENTITLEMENTS_FILE`.
- If macOS blocks the first launch because the app is unsigned, right-click the app in Finder and choose **Open** once to approve it.

## Python Version

`spotdl` currently requires Python `<3.14`, so this repo pins `3.11.13` via `.python-version`. The `./setup`, `./dev`, and `./run` scripts use that environment automatically.

## Spotify Credentials

Spotify links rely on Spotify API credentials loaded by `spotdl`, usually from `~/.spotdl/config.json`.

If you start seeing HTTP 429 or `Retry-After` responses for every Spotify link, the current credentials are rate limited. Update the `client_id` and `client_secret` in `~/.spotdl/config.json`, or override them when launching the app:

```bash
SPOTDL_CLIENT_ID=your_client_id SPOTDL_CLIENT_SECRET=your_client_secret ./dev
```

## Acknowledgments

- Built on top of the excellent [spotDL](https://github.com/spotDL/spotify-downloader) project
