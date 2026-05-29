# MuMu Cross-Platform Capture App Design

## Context

The current project is a small mitmproxy addon:

- `dewu_image_saver.py` intercepts Dewu-related image and video responses, converts images to RGB JPEG, and saves media to local folders.
- `README.md` documents a command-line workflow using `mitmdump -s dewu_image_saver.py`.
- The previous runtime environment is MuMu Player, and the new app should continue using MuMu rather than replacing it with a real-phone workflow.

The first version should replace the command-line experience with a desktop app while preserving the existing capture mechanism.

## Goals

- Provide a cross-platform desktop app for Windows and macOS.
- Continue using MuMu Player as the Android runtime.
- Keep mitmproxy and the existing Python capture logic as the capture core.
- Let users start and stop capture from a UI.
- Show proxy information needed by MuMu.
- Display capture logs, saved images, and saved videos.
- Avoid fragile first-version automation for MuMu proxy and certificate setup.

## Cross-Platform Requirement

Windows and macOS support is mandatory. Future implementation work must preserve both platforms unless the user explicitly approves a platform-specific change.

- Windows must support MuMu Player, MuMu bundled `adb.exe`, PowerShell-friendly setup commands, `npm.cmd`, and MSVC/Tauri requirements.
- macOS must support MuMu Player for macOS, bundled or PATH `adb`, `python3`, Homebrew-style paths such as `/opt/homebrew/bin` and `/usr/local/bin`, and macOS Tauri requirements.
- OS-specific behavior should live behind `cfg(target_os = "...")`, runtime platform checks, or clearly named helper functions.
- Setup UI and docs must stay paired: when environment setup changes, update both Windows and macOS instructions.
- Avoid hard-coded Windows-only or macOS-only paths and commands unless an equivalent fallback exists.

## Non-Goals

- Do not build a mobile app that directly captures another app's traffic.
- Do not replace mitmproxy with a custom proxy in the first version.
- Do not require automatic MuMu configuration in the first version.
- Do not attempt to bypass certificate pinning or app security controls.

## Recommended Approach

Use Tauri for the desktop shell and keep Python plus mitmproxy as a sidecar process.

```text
Tauri Desktop App
+-- Frontend UI
|   +-- Capture status
|   +-- Proxy setup panel
|   +-- Image gallery
|   +-- Video gallery
|   +-- Logs
|   +-- Settings
+-- Tauri/Rust backend
|   +-- Start and stop mitmdump
|   +-- Stream process logs to UI
|   +-- Read and write local settings
|   +-- Watch output folders
|   +-- Open output folders in the OS file manager
+-- Python capture sidecar
    +-- mitmproxy addon
    +-- Dewu host filtering
    +-- image conversion
    +-- video saving
    +-- structured logging
```

This approach keeps the proven capture path and focuses product work on control, observability, and file management.

## Application Screens

### Capture

The capture screen is the default screen. It shows:

- Capture state: stopped, starting, running, stopping, or error.
- Start and stop controls.
- Local proxy address, such as `192.168.1.23:8080`.
- Output counters for images and videos.
- Recent save events and conversion errors.

The app should detect the best local LAN IPv4 address and allow manual override.

### MuMu Setup

The setup screen gives concise steps for configuring MuMu manually:

- Configure Android Wi-Fi proxy to the displayed host and port.
- Visit `http://mitm.it` inside MuMu to install the certificate.
- Trust the certificate according to the Android version used by MuMu.
- Open Dewu and browse products normally.

This page should be treated as guided setup, not marketing or long documentation.

### Gallery

The gallery has two tabs:

- Images: thumbnails from `images/`, sorted newest first.
- Videos: files from `videos/`, sorted newest first.

Expected actions:

- Open file.
- Open containing folder.
- Delete selected file.
- Clear all files with confirmation.
- Refresh list.

Image details should include file size, saved time, and dimensions when available.

### Logs

The logs screen shows:

- mitmdump process output.
- capture save events.
- conversion failures.
- proxy startup errors.

Logs should be visible in the app and also written to a local file for debugging.

### Settings

Initial settings:

- Proxy port, default `8080`.
- Output root directory, default project/app data directory.
- Debug logging toggle.
- Dewu host keyword list, with safe defaults.
- JPEG quality, default `95`.

Settings should be stored locally and passed to the Python capture sidecar at startup.

## Capture Sidecar Changes

The existing `dewu_image_saver.py` should be refactored into a configurable sidecar:

- Read configuration from environment variables or a small JSON config file.
- Allow output directory, debug mode, JPEG quality, and host keywords to be configured.
- Emit structured line logs that the desktop app can parse.
- Keep image conversion behavior compatible with ERP upload requirements.
- Keep video capture support, but make it visible in README and UI.

Example structured log shape:

```json
{"event":"image_saved","file":"abc123.jpg","bytes":123456,"url_hash":"abc123"}
{"event":"video_saved","file":"def456.mp4","bytes":987654,"url_hash":"def456"}
{"event":"convert_failed","error":"cannot identify image file","url":"https://..."}
```

## Data Flow

1. User opens the desktop app.
2. App loads settings and detects local proxy IP.
3. User starts capture.
4. Tauri backend starts `mitmdump` with the Python addon and selected port.
5. User manually configures MuMu proxy to the displayed address.
6. MuMu traffic flows through mitmproxy.
7. Python sidecar saves images and videos.
8. App watches output folders and updates galleries.
9. App streams sidecar logs into the logs screen.

## Error Handling

- If the selected port is in use, show a clear error and let the user choose another port.
- If `mitmdump` or Python dependencies are missing, show installation or packaging guidance.
- If no LAN IP is detected, fall back to `127.0.0.1` and let the user manually enter an address.
- If image conversion fails, skip that file and log the URL plus error.
- If output folders cannot be written, stop capture and show the failing path.

## Packaging

The preferred packaging model is:

- Bundle the Tauri app normally for Windows and macOS.
- Bundle Python, mitmproxy, Pillow, and pillow-heif as a sidecar runtime if feasible.
- During early development, allow using the developer's installed Python environment.

Packaging should be solved after the UI and sidecar contract are stable, because mitmproxy packaging is the riskiest part.

## Phase 1 Scope

Phase 1 includes:

- Tauri app scaffold.
- Capture start and stop.
- Configurable port and output directory.
- Local proxy address display.
- Folder watching for `images/` and `videos/`.
- Image and video gallery.
- Log streaming.
- Updated README for the MuMu desktop app workflow.

Phase 1 excludes:

- Automatic MuMu launch.
- Automatic proxy setup through ADB.
- Automatic CA certificate installation.
- Product grouping or advanced media filtering.

## Phase 2 Scope

Phase 2 may add:

- ADB detection for MuMu.
- One-click Dewu app launch.
- Automatic certificate push where supported.
- Best-effort proxy setup.
- Media filtering by dimensions, file size, or URL pattern.
- Export profiles for ERP workflows.

## Testing

Manual tests:

- Start and stop capture repeatedly.
- Verify port conflict handling.
- Save sample images and videos through mitmproxy.
- Confirm gallery updates without app restart.
- Confirm delete, clear, and open-folder actions.
- Confirm logs show startup, save, and error events.

Sidecar tests:

- Unit-test Dewu host matching.
- Unit-test image and video response classification.
- Unit-test RGB JPEG conversion for RGB, RGBA, palette, and CMYK inputs.
- Unit-test config parsing.

## Open Decisions

- Frontend framework: React is the default unless the user prefers Vue or Svelte.
- Packaging strategy: decide after the development version works.
- Output directory default: project-local during development, app data directory after packaging.
