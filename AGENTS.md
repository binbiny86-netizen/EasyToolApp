# Project Requirements for Agents

## Cross-Platform Requirement

This app must remain usable on both Windows and macOS.

When changing capture, setup, packaging, environment detection, process management, file opening, path handling, ADB integration, Python/mitmproxy launching, or documentation, preserve both platforms unless the user explicitly approves a platform-specific change.

Required behavior:

- Windows continues to support MuMu Player, MuMu bundled `adb.exe`, PowerShell-friendly commands, `npm.cmd`, and MSVC/Tauri requirements.
- macOS supports MuMu Player for macOS, bundled or PATH `adb`, `python3`, Homebrew-style paths such as `/opt/homebrew/bin` and `/usr/local/bin`, and macOS Tauri requirements.
- Platform-specific logic belongs behind `cfg(target_os = "...")`, runtime platform checks, or clearly named helper functions.
- UI setup instructions must include both Windows and macOS whenever environment setup changes.
- Documentation changes must keep `docs/macos.md` and the Windows workflow consistent with the app.
- Avoid hard-coding Windows-only assumptions such as `.exe`, `where.exe`, `py`, PowerShell, backslash-only paths, or `C:\`/`D:\` paths without a macOS equivalent or fallback.
- Avoid hard-coding macOS-only assumptions such as Homebrew paths or `open` without a Windows equivalent or fallback.

Verification expectation:

- Run `npm.cmd run build` on Windows or `npm run build` on macOS.
- Run `cargo check` from `src-tauri`.
- If touching frontend UI, verify the local page renders.
- If touching platform integration, note which platform was actually tested and which still needs real-machine validation.

## Current Runtime Shape

- Desktop shell: Tauri 2 + React.
- Capture core: Python `dewu_image_saver.py` launched through `mitmdump`.
- Android runtime: MuMu Player remains the supported emulator path.
- Proxy setup: App can set and clear MuMu Android Wi-Fi proxy through ADB.
- User must still install/trust the mitmproxy certificate inside MuMu.
