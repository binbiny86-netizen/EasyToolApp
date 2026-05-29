# Project Requirements

## Platform Support

The app is required to support both Windows and macOS.

Cross-platform support is a product requirement, not a best-effort cleanup task. Future changes must keep the Windows and macOS workflows working unless the user explicitly decides to drop or postpone one platform.

## Supported Workflows

Windows:

- Run the Tauri desktop app.
- Use MuMu Player as the Android runtime.
- Detect MuMu bundled `adb.exe` when possible.
- Allow manual ADB path override through `MUMU_ADB`.
- Launch `mitmdump` through the current Python environment or a configured command.
- Use PowerShell-friendly setup commands in the UI and docs.

macOS:

- Run the Tauri desktop app.
- Use MuMu Player for macOS as the Android runtime.
- Detect MuMu bundled `adb` from common `.app` locations, `PATH`, or `MUMU_ADB`.
- Launch `mitmdump` through `python3`, Homebrew paths, or a configured command.
- Use macOS-friendly setup commands in the UI and docs.

Both platforms:

- The listening port must remain configurable.
- The app must not assume `127.0.0.1` is valid for MuMu proxy traffic; users should use the computer LAN IP.
- The app must keep ADB proxy setup and clearing available when ADB is detected.
- The app must show clear errors for missing dependencies, busy ports, unreachable proxy targets, and missing ADB.
- The app must keep image/video gallery, preview, pagination, deletion, and filtering behavior platform-neutral.

## Implementation Rules

- Put OS-specific backend behavior behind `cfg(target_os = "...")` or clearly named platform helper functions.
- Do not introduce Windows-only path, process, or command assumptions without a macOS path.
- Do not introduce macOS-only path, process, or command assumptions without a Windows path.
- Prefer configurable commands and paths over fixed install locations.
- Keep environment setup instructions on the homepage in sync for Windows and macOS.
- Keep `docs/macos.md` updated when macOS setup or runtime behavior changes.

## Verification Rules

For every change:

- Run frontend build: `npm.cmd run build` on Windows or `npm run build` on macOS.
- Run Rust check: `cargo check` in `src-tauri`.
- For UI changes, verify the local app page renders.

For platform integration changes:

- State which OS was actually tested.
- If a platform was not tested on a real machine, leave a clear note in the final response.
