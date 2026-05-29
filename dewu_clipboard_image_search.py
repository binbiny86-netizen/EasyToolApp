"""
Copy an image on Windows, show it on the desktop, open Dewu image search,
then tap Dewu's real-time screen capture option.

Typical flow:
1. Copy one product image on Windows.
2. Run:
   py dewu_clipboard_image_search.py

If Dewu layout is different, adjust --entry-x/--entry-y or --screen-x/--screen-y.
"""

from __future__ import annotations

import argparse
import ctypes
import datetime as dt
import os
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from ctypes import wintypes

try:
    from PIL import Image, ImageGrab
except ImportError:
    Image = None
    ImageGrab = None


DEFAULT_ADB_CANDIDATES = [
    r"D:\Software\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    r"D:\Software\MuMuPlayer\nx_device\11.0\shell\adb.exe",
    r"D:\Software\MuMuPlayer-12.0\shell\adb.exe",
    r"D:\Software\MuMuPlayer\shell\adb.exe",
]

MUMU_PORTS = [7555, 5555, 16384, 16416]
DEWU_PACKAGES = ["com.shizhuang.duapp", "com.dewu.app"]
DEFAULT_REMOTE_DIR = "/sdcard"
REMOTE_DIR_FALLBACKS = [
    "/sdcard",
    "/sdcard/Pictures/DewuSearch",
    "/sdcard/Download/DewuSearch",
    "/sdcard/DCIM/Camera",
]
PHOTO_SEARCH_RESOURCE_HINTS = ["ivPhotoSearch", "photoSearch", "PhotoSearch", "ivCamera"]
PHOTO_SEARCH_TEXT_HINTS = ["识图", "拍照搜", "图片搜索", "搜同款", "相册", "拍照"]
REALTIME_SCREEN_TEXT_HINTS = ["实时截屏", "截取电脑画面扫描"]
PREVIEW_WINDOW_TITLE = "得物实时截屏图片"
CAPTURE_WINDOW_TITLE_HINTS = ["实时截屏", "拖动窗口实时获取图像", "实时获取图像"]
POPUP_TEXT_HINTS = ["同意", "允许", "知道了", "我知道了", "暂不", "以后再说", "取消"]


class ScriptError(RuntimeError):
    pass


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def main() -> int:
    args = parse_args()
    if args.preview_image:
        return run_preview_window(Path(args.preview_image), args.preview_seconds)

    try:
        adb = resolve_adb(args.adb)
        device = resolve_device(adb, args.device)
        local_image = save_clipboard_image(args.local_dir, args.quality)

        remote_image = ""
        if args.method == "album":
            remote_image = push_image(adb, device, local_image, args.remote_dir)
            scan_media(adb, device, remote_image)
            wait_for_media_index(adb, device, remote_image, args.media_timeout)

        if not args.manual_picker and not args.no_open_dewu:
            open_dewu(adb, device, args.package, restart=not args.no_restart_dewu)
            close_common_popups(adb, device)

        if not args.manual_picker:
            open_dewu_image_search(adb, device, args)
            close_common_popups(adb, device)

        if args.method == "screen" and not args.no_tap:
            tap_realtime_screen(adb, device, args)
            start_preview_window(local_image, args.preview_seconds)
            time.sleep(args.preview_wait)
            maximize_capture_and_preview(args)
        else:
            if args.upload_x is not None and args.upload_y is not None:
                tap(adb, device, args.upload_x, args.upload_y, "tap upload entry")
                time.sleep(args.wait_after_upload)

        if args.method == "album" and not args.no_tap:
            x, y = resolve_photo_tap(adb, device, args.photo_x, args.photo_y)
            time.sleep(args.wait_before_tap)
            tap(adb, device, x, y, "tap newest imported image")

        print("\nDone.")
        print(f"ADB: {adb}")
        print(f"Device: {device}")
        print(f"Local image: {local_image}")
        if remote_image:
            print(f"MuMu image: {remote_image}")
        if args.method == "album" and not args.no_tap:
            print("If the wrong area was tapped, rerun with --entry-x/--entry-y or --photo-x/--photo-y.")
        if args.method == "screen":
            print("If the real-time screen option was missed, rerun with --screen-x and --screen-y.")
        return 0
    except ScriptError as error:
        print(f"错误：{error}", file=sys.stderr)
        return 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Use the Windows clipboard image for Dewu image search in MuMu.")
    parser.add_argument("--preview-image", help=argparse.SUPPRESS)
    parser.add_argument("--preview-seconds", type=float, default=45.0, help=argparse.SUPPRESS)
    parser.add_argument("--method", choices=["screen", "album"], default="screen", help="Search method. screen uses Dewu real-time screen capture; album imports into Android gallery.")
    parser.add_argument("--adb", help="Path to adb.exe. Defaults to MuMu adb or adb from PATH.")
    parser.add_argument("--device", help="ADB device serial. Defaults to the connected MuMu device.")
    parser.add_argument("--local-dir", default="clipboard_uploads", help="Where to save clipboard images locally.")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR, help="Android directory used for imported images.")
    parser.add_argument("--quality", type=int, default=95, help="JPEG quality for clipboard image export.")
    parser.add_argument("--media-timeout", type=float, default=8.0, help="Seconds to wait until Android media library sees the image.")
    parser.add_argument("--manual-picker", action="store_true", help="Assume Dewu's photo picker is already open.")
    parser.add_argument("--no-open-dewu", action="store_true", help="Do not launch Dewu before opening image search.")
    parser.add_argument("--no-restart-dewu", action="store_true", help="Do not force-stop Dewu before launching it.")
    parser.add_argument("--no-tap", action="store_true", help="Only import/open image search; do not tap the picker.")
    parser.add_argument("--entry-x", type=int, help="Fallback X coordinate for Dewu image-search entry.")
    parser.add_argument("--entry-y", type=int, help="Fallback Y coordinate for Dewu image-search entry.")
    parser.add_argument("--screen-x", type=int, help="Fallback X coordinate for Dewu real-time screen option.")
    parser.add_argument("--screen-y", type=int, help="Fallback Y coordinate for Dewu real-time screen option.")
    parser.add_argument("--photo-x", type=int, help="X coordinate for the newest image thumbnail.")
    parser.add_argument("--photo-y", type=int, help="Y coordinate for the newest image thumbnail.")
    parser.add_argument("--upload-x", type=int, help="Optional X coordinate to tap Dewu's upload/photo entry first.")
    parser.add_argument("--upload-y", type=int, help="Optional Y coordinate to tap Dewu's upload/photo entry first.")
    parser.add_argument("--wait-before-tap", type=float, default=1.2, help="Seconds to wait before tapping photo.")
    parser.add_argument("--wait-after-upload", type=float, default=1.5, help="Seconds to wait after tapping upload.")
    parser.add_argument("--wait-after-entry", type=float, default=2.0, help="Seconds to wait after opening image search.")
    parser.add_argument("--preview-wait", type=float, default=0.8, help="Seconds to wait after showing the desktop preview.")
    parser.add_argument("--capture-window-timeout", type=float, default=5.0, help="Seconds to wait for MuMu real-time capture window.")
    parser.add_argument("--capture-padding", type=int, default=24, help="Extra pixels around the preview when positioning MuMu capture window.")
    parser.add_argument("--no-align-capture-window", action="store_true", help="Do not move the MuMu real-time capture window.")
    parser.add_argument("--adb-screen-clicks", action="store_true", help="Use ADB taps instead of Windows mouse clicks for MuMu screen-capture controls.")
    parser.add_argument("--open-dewu", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--package", help="Dewu Android package name. Defaults to auto-detect.")
    return parser.parse_args()


def start_preview_window(image_path: Path, seconds: float) -> None:
    close_preview_windows()
    executable = python_gui_executable()
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [str(executable), str(Path(__file__).resolve()), "--preview-image", str(image_path), "--preview-seconds", str(seconds)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
    )
    print(f"desktop preview opened: {image_path}")
    wait_for_window(PREVIEW_WINDOW_TITLE, 3.0)


def close_preview_windows() -> None:
    if os.name != "nt":
        return

    user32 = ctypes.windll.user32
    targets: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        if get_window_text(hwnd) == PREVIEW_WINDOW_TITLE:
            targets.append(hwnd)
        return True

    user32.EnumWindows(enum_proc, 0)
    for hwnd in targets:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)


def python_gui_executable() -> Path:
    current = Path(sys.executable)
    if os.name == "nt":
        pythonw = current.with_name("pythonw.exe")
        if pythonw.exists():
            return pythonw
    return current


def run_preview_window(image_path: Path, seconds: float) -> int:
    if Image is None:
        return 1
    try:
        import tkinter as tk
        from PIL import ImageTk
    except Exception:
        return 1

    image = Image.open(image_path)
    root = tk.Tk()
    root.title(PREVIEW_WINDOW_TITLE)
    root.configure(bg="#111111")
    root.overrideredirect(True)
    root.attributes("-topmost", True)

    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    max_width = screen_width
    max_height = screen_height
    original_image = image.copy()
    preview_image = image.copy()
    preview_image.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)

    canvas = tk.Canvas(root, bg="#111111", highlightthickness=0, bd=0)
    canvas.pack(fill="both", expand=True)
    canvas.image = None

    def render_image(event: object | None = None) -> None:
        width_now = max(1, canvas.winfo_width())
        height_now = max(1, canvas.winfo_height())
        fitted = original_image.copy()
        fitted.thumbnail((width_now, height_now), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(fitted)
        canvas.delete("all")
        canvas.create_image(width_now // 2, height_now // 2, image=photo, anchor="center")
        canvas.image = photo

    canvas.bind("<Configure>", render_image)

    width = screen_width
    height = screen_height
    x = 0
    y = 0
    root.geometry(f"{width}x{height}+{x}+{y}")
    root.after(50, render_image)
    root.after(round(max(5.0, seconds) * 1000), root.destroy)
    root.mainloop()
    return 0


def resolve_adb(adb_arg: str | None) -> Path:
    candidates: list[Path] = []
    if adb_arg:
        candidates.append(Path(adb_arg))
    candidates.extend(Path(path) for path in DEFAULT_ADB_CANDIDATES)

    path_adb = shutil.which("adb")
    if path_adb:
        candidates.append(Path(path_adb))

    for candidate in candidates:
        if candidate.exists():
            return candidate

    raise ScriptError(
        "adb.exe not found. Pass --adb, or install/start MuMu so its adb path exists."
    )


def resolve_device(adb: Path, device_arg: str | None) -> str:
    if device_arg:
        return device_arg

    devices = adb_devices(adb)
    for device in devices:
        if device.startswith("127.0.0.1:"):
            return device

    connect_logs = []
    for port in MUMU_PORTS:
        target = f"127.0.0.1:{port}"
        result = run([adb, "connect", target], check=False)
        connect_logs.append(result.strip())
        if target in adb_devices(adb):
            return target

    raise ScriptError(
        "No MuMu ADB device found. Start MuMu first. Tried ports "
        f"{MUMU_PORTS}. Output: {' | '.join(connect_logs)}"
    )


def adb_devices(adb: Path) -> list[str]:
    output = run([adb, "devices"])
    devices = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def save_clipboard_image(local_dir: str, quality: int) -> Path:
    if Image is None or ImageGrab is None:
        raise ScriptError("缺少 Pillow 依赖，请先运行：py -m pip install Pillow")

    grabbed = ImageGrab.grabclipboard()
    if grabbed is None:
        raise ScriptError("剪贴板里没有图片。请先复制一张图片，再点击“剪贴板识图”。")

    output_dir = Path(local_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    output = output_dir / f"dewu_clipboard_{stamp}.jpg"

    if isinstance(grabbed, Image.Image):
        image = grabbed
    elif isinstance(grabbed, list):
        image = load_first_image_file(grabbed)
    else:
        raise ScriptError(f"剪贴板内容不是图片，当前类型：{type(grabbed)!r}")

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")

    image.save(output, "JPEG", quality=max(1, min(100, quality)), optimize=True)
    return output


def load_first_image_file(paths: list[str]) -> Image.Image:
    image_exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
    for item in paths:
        path = Path(item)
        if path.suffix.lower() in image_exts and path.exists():
            return Image.open(path)
    raise ScriptError("剪贴板里是文件，但没有找到支持的图片文件。请复制 jpg、png、webp 或 bmp 图片。")


def push_image(adb: Path, device: str, local_image: Path, remote_dir: str) -> str:
    errors = []
    for candidate in remote_dir_candidates(remote_dir):
        candidate = candidate.rstrip("/")
        remote_image = f"{candidate}/{local_image.name}"
        mkdir_output = run([adb, "-s", device, "shell", "mkdir", "-p", candidate], check=False)
        if "Permission denied" in mkdir_output:
            errors.append(f"{candidate}: {mkdir_output.strip()}")
            continue

        push_output = run([adb, "-s", device, "push", str(local_image), remote_image], check=False)
        if "Permission denied" in push_output or "failed" in push_output.lower():
            errors.append(f"{candidate}: {push_output.strip()}")
            continue

        print(f"uploaded to: {remote_image}")
        return remote_image

    raise ScriptError(
        "Failed to upload image to MuMu. Tried directories:\n" + "\n".join(errors)
    )


def remote_dir_candidates(remote_dir: str) -> list[str]:
    candidates = [remote_dir]
    candidates.extend(REMOTE_DIR_FALLBACKS)
    deduped = []
    for candidate in candidates:
        normalized = candidate.rstrip("/")
        if normalized and normalized not in deduped:
            deduped.append(normalized)
    return deduped


def scan_media(adb: Path, device: str, remote_image: str) -> None:
    uri = f"file://{remote_image}"
    remote_dir = remote_image.rsplit("/", 1)[0]
    commands = [
        [adb, "-s", device, "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", uri],
        [adb, "-s", device, "shell", "cmd", "media", "scan", remote_image],
        [adb, "-s", device, "shell", "cmd", "media", "scan", remote_dir],
    ]
    for command in commands:
        run(command, check=False)


def wait_for_media_index(adb: Path, device: str, remote_image: str, timeout: float) -> None:
    filename = remote_image.rsplit("/", 1)[-1]
    deadline = time.monotonic() + max(0.0, timeout)
    last_output = ""

    while True:
        output = query_media_store(adb, device, filename)
        last_output = output.strip()
        if filename in output:
            print(f"media indexed: {filename}")
            return
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)

    scan_media(adb, device, remote_image)
    time.sleep(1.0)
    output = query_media_store(adb, device, filename)
    if filename in output:
        print(f"media indexed after retry: {filename}")
        return

    print(f"warning: media library did not confirm {filename}; continuing anyway.")
    if last_output and "Error while accessing provider" not in last_output:
        print(last_output)


def query_media_store(adb: Path, device: str, filename: str) -> str:
    where = f'_display_name=\\"{filename}\\"'
    output = run(
        [
            adb,
            "-s",
            device,
            "shell",
            "content",
            "query",
            "--uri",
            "content://media/external/images/media",
            "--where",
            where,
        ],
        check=False,
    )
    if filename in output:
        return output

    all_output = run(
        [
            adb,
            "-s",
            device,
            "shell",
            "content",
            "query",
            "--uri",
            "content://media/external/images/media",
        ],
        check=False,
    )
    if filename in all_output:
        return all_output
    return ""


def open_dewu(adb: Path, device: str, package_arg: str | None, restart: bool) -> None:
    package = package_arg or detect_dewu_package(adb, device)
    if restart:
        run([adb, "-s", device, "shell", "am", "force-stop", package], check=False)
        time.sleep(0.8)
    run([adb, "-s", device, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"])
    time.sleep(3.0 if restart else 2.0)


def detect_dewu_package(adb: Path, device: str) -> str:
    output = run([adb, "-s", device, "shell", "pm", "list", "packages"], check=False)
    for package in DEWU_PACKAGES:
        if f"package:{package}" in output:
            return package
    for line in output.splitlines():
        package = line.removeprefix("package:").strip()
        lower = package.lower()
        if "dewu" in lower or "duapp" in lower or "shizhuang" in lower:
            return package
    raise ScriptError("Dewu package was not found. Pass --package if needed.")


def open_dewu_image_search(adb: Path, device: str, args: argparse.Namespace) -> None:
    if args.entry_x is not None and args.entry_y is not None:
        tap(adb, device, args.entry_x, args.entry_y, "tap Dewu image-search entry")
        time.sleep(args.wait_after_entry)
        return

    root = dump_ui(adb, device, check=False)
    node = None
    if root is not None:
        node = find_node_by_resource(root, PHOTO_SEARCH_RESOURCE_HINTS)
        if node is None:
            node = find_node_by_text(root, PHOTO_SEARCH_TEXT_HINTS)

    if node is not None:
        x, y = node_center(node)
        label = node.get("resource-id") or node.get("text") or node.get("content-desc") or "matched node"
        tap(adb, device, x, y, f"tap Dewu image-search entry: {label}")
        time.sleep(args.wait_after_entry)
        return

    width, height = wm_size(adb, device)
    # Current Dewu builds put the photo-search icon inside the top search bar.
    x = round(width * 0.63)
    y = round(height * 0.07)
    tap(adb, device, x, y, "tap Dewu image-search entry fallback")
    time.sleep(args.wait_after_entry)


def tap_realtime_screen(adb: Path, device: str, args: argparse.Namespace) -> None:
    if args.screen_x is not None and args.screen_y is not None:
        tap_screen_control(adb, device, args.screen_x, args.screen_y, "tap real-time screen option", args)
        time.sleep(args.wait_after_upload)
        require_capture_window(args)
        return

    open_scan_dialog_if_needed(adb, device, args)

    if find_capture_window() is not None:
        return

    if not getattr(args, "adb_screen_clicks", False) and click_mumu_realtime_source_window():
        time.sleep(args.wait_after_upload)
        require_capture_window(args)
        return

    root = dump_ui(adb, device, check=False)
    node = None
    if root is not None:
        node = find_node_by_text(root, REALTIME_SCREEN_TEXT_HINTS)

    if node is not None:
        x, y = node_center(node)
        tap(adb, device, x, y, f"tap real-time screen option: {node.get('text') or node.get('content-desc')}")
        time.sleep(args.wait_after_upload)
        require_capture_window(args)
        return

    width, height = wm_size(adb, device)
    tap_screen_control(
        adb,
        device,
        round(width * 0.50),
        round(height * 0.405),
        "tap real-time screen option fallback",
        args,
    )
    time.sleep(args.wait_after_upload)
    require_capture_window(args)


def require_capture_window(args: argparse.Namespace) -> int:
    capture = wait_for_capture_window(args.capture_window_timeout)
    if capture is None:
        raise ScriptError("没有检测到 MuMu 的实时截屏窗口。请确认得物已在拍照搜索页，并且 MuMu 顶部“扫码”菜单里有“实时截屏”。")
    return capture


def click_mumu_realtime_source_window(timeout: float = 2.0) -> bool:
    source_window = wait_for_mumu_source_window(timeout)
    if source_window is None:
        return False

    put_preview_behind()
    left, top, _right, _bottom = get_window_rect(source_window)
    windows_click(left + 185, top + 88)
    print("tap MuMu real-time screen source by Windows mouse")
    return True


def wait_for_mumu_source_window(timeout: float) -> int | None:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        hwnd = find_mumu_source_window()
        if hwnd is not None:
            return hwnd
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)


def find_mumu_source_window() -> int | None:
    if os.name != "nt":
        return None

    user32 = ctypes.windll.user32
    candidates: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        text = get_window_text(hwnd)
        class_name = get_window_class_name(hwnd)
        if text != "MuMuNxDevice" or class_name != "Qt5156QWindow":
            return True
        left, top, right, bottom = get_window_rect(hwnd)
        width = right - left
        height = bottom - top
        if 200 <= width <= 500 and 200 <= height <= 500:
            candidates.append((width * height, hwnd))
        return True

    user32.EnumWindows(enum_proc, 0)
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def open_scan_dialog_if_needed(adb: Path, device: str, args: argparse.Namespace) -> None:
    root = dump_ui(adb, device, check=False)
    if root is None:
        return
    if find_node_by_text(root, REALTIME_SCREEN_TEXT_HINTS) is not None:
        return

    scan_node = find_node_by_text(root, ["扫码"], exact=True)
    width, height = wm_size(adb, device)
    if scan_node is None:
        tap_screen_control(
            adb,
            device,
            round(width * 0.906),
            round(height * 0.092),
            "tap scan option fallback",
            args,
        )
    else:
        x, y = node_center(scan_node)
        tap_screen_control(adb, device, x, y, "tap scan option", args)
    time.sleep(1.0)


def tap_screen_control(adb: Path, device: str, x: int, y: int, label: str, args: argparse.Namespace) -> None:
    if not getattr(args, "adb_screen_clicks", False) and windows_click_android_point(x, y):
        print(f"{label} by Windows mouse: ({x}, {y})")
        return
    tap(adb, device, x, y, label)


def windows_click_android_point(android_x: int, android_y: int) -> bool:
    if os.name != "nt":
        return False
    hwnd = find_mumu_window()
    if hwnd is None:
        return False

    put_preview_behind()
    bring_window_to_front(hwnd)
    left, top, width, height = get_client_rect_on_screen(hwnd)
    scale = min(width / 1440, height / 2560)
    content_width = 1440 * scale
    content_height = 2560 * scale
    offset_x = (width - content_width) / 2
    offset_y = (height - content_height) / 2
    screen_x = round(left + offset_x + android_x * scale)
    screen_y = round(top + offset_y + android_y * scale)
    windows_click(screen_x, screen_y)
    return True


def put_preview_behind() -> None:
    preview = find_window_by_title(PREVIEW_WINDOW_TITLE)
    if preview is None:
        return
    set_window_topmost(preview, False)
    send_window_to_bottom(preview)


def find_mumu_window() -> int | None:
    if os.name != "nt":
        return None
    user32 = ctypes.windll.user32
    candidates: list[tuple[int, int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        text = get_window_text(hwnd)
        if "MuMu" not in text:
            return True
        class_name = get_window_class_name(hwnd)
        if "得物 MuMu 采集" in text or class_name in {"Tauri Window", "Chrome_WidgetWin_1"}:
            return True
        left, top, right, bottom = get_window_rect(hwnd)
        width = max(0, right - left)
        height = max(0, bottom - top)
        area = width * height
        if area > 100_000:
            score = 0
            if "MuMu安卓设备" in text:
                score += 100
            elif "MuMuNxDevice" in text:
                score += 85
            elif "MuMu模拟器" in text:
                score += 60
            if class_name.startswith("Qt"):
                score += 20
            if height > width:
                score += 15
            candidates.append((score, area, hwnd))
        return True

    user32.EnumWindows(enum_proc, 0)
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][2]


def get_client_rect_on_screen(hwnd: int) -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    point = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(point))
    return point.x, point.y, rect.right - rect.left, rect.bottom - rect.top


def windows_click(x: int, y: int) -> None:
    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    time.sleep(0.05)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def maximize_capture_and_preview(args: argparse.Namespace) -> None:
    if args.no_align_capture_window or os.name != "nt":
        return

    preview = wait_for_window(PREVIEW_WINDOW_TITLE, 1.0)
    capture = wait_for_capture_window(args.capture_window_timeout)
    if preview is None:
        print("warning: preview window was not found; cannot align it to MuMu capture window.")
        return
    if capture is None:
        print("warning: MuMu real-time capture window was not found.")
        return

    x, y, width, height = screen_bounds_for_window(capture)
    width = max(200, width)
    height = max(200, height)
    move_window(preview, x, y, width, height)
    set_window_topmost(preview, False)
    send_window_to_bottom(preview)
    move_window(capture, x, y, width, height)
    set_window_topmost(capture, True)
    bring_window_to_front(capture)
    print(f"fullscreen MuMu capture and preview windows: ({x}, {y}, {width}, {height})")


def wait_for_capture_window(timeout: float) -> int | None:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        hwnd = find_capture_window()
        if hwnd is not None:
            return hwnd
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)


def find_capture_window() -> int | None:
    if os.name != "nt":
        return None

    user32 = ctypes.windll.user32
    matches: list[tuple[int, int]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        text = get_window_text(hwnd)
        if text == PREVIEW_WINDOW_TITLE:
            return True
        if not any(hint in text for hint in CAPTURE_WINDOW_TITLE_HINTS):
            return True
        class_name = get_window_class_name(hwnd)
        if not class_name.startswith("Qt"):
            return True
        left, top, right, bottom = get_window_rect(hwnd)
        area = max(0, right - left) * max(0, bottom - top)
        matches.append((area, hwnd))
        return True

    user32.EnumWindows(enum_proc, 0)
    if not matches:
        return None
    matches.sort(reverse=True)
    return matches[0][1]


def screen_bounds_for_window(hwnd: int) -> tuple[int, int, int, int]:
    if os.name != "nt":
        return 0, 0, 1920, 1080

    user32 = ctypes.windll.user32
    monitor = user32.MonitorFromWindow(hwnd, 2)
    info = MONITORINFO()
    info.cbSize = ctypes.sizeof(MONITORINFO)
    if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return (
            info.rcMonitor.left,
            info.rcMonitor.top,
            info.rcMonitor.right - info.rcMonitor.left,
            info.rcMonitor.bottom - info.rcMonitor.top,
        )

    return (
        user32.GetSystemMetrics(76),
        user32.GetSystemMetrics(77),
        user32.GetSystemMetrics(78),
        user32.GetSystemMetrics(79),
    )


def wait_for_window(title: str | list[str], timeout: float) -> int | None:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        hwnd = find_window_by_title(title)
        if hwnd:
            return hwnd
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.2)


def find_window_by_title(title: str | list[str]) -> int | None:
    if os.name != "nt":
        return None
    hints = [title] if isinstance(title, str) else title
    hints = [hint.lower() for hint in hints]
    user32 = ctypes.windll.user32
    matches: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def enum_proc(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        text = get_window_text(hwnd).lower()
        if text and any(hint in text for hint in hints):
            matches.append(hwnd)
            return False
        return True

    user32.EnumWindows(enum_proc, 0)
    return matches[0] if matches else None


def get_window_text(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(512)
    ctypes.windll.user32.GetWindowTextW(hwnd, buffer, len(buffer))
    return buffer.value


def get_window_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetClassNameW(hwnd, buffer, len(buffer))
    return buffer.value


def get_window_rect(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def move_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    ctypes.windll.user32.MoveWindow(hwnd, x, y, width, height, True)


def set_window_topmost(hwnd: int, topmost: bool) -> None:
    insert_after = -1 if topmost else -2
    ctypes.windll.user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)


def send_window_to_bottom(hwnd: int) -> None:
    ctypes.windll.user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040)


def bring_window_to_front(hwnd: int) -> None:
    user32 = ctypes.windll.user32
    user32.ShowWindow(hwnd, 5)
    user32.SetForegroundWindow(hwnd)


def close_common_popups(adb: Path, device: str) -> None:
    for _ in range(3):
        root = dump_ui(adb, device, check=False)
        if root is None:
            return
        node = find_node_by_text(root, POPUP_TEXT_HINTS, exact=True)
        if node is None:
            return
        x, y = node_center(node)
        tap(adb, device, x, y, f"tap popup: {node.get('text') or node.get('content-desc')}")
        time.sleep(0.8)


def resolve_photo_tap(adb: Path, device: str, x_arg: int | None, y_arg: int | None) -> tuple[int, int]:
    if x_arg is not None and y_arg is not None:
        return x_arg, y_arg
    root = dump_ui(adb, device, check=False)
    if root is not None:
        node = find_picker_thumbnail(root)
        if node is not None:
            return node_center(node)
    width, height = wm_size(adb, device)
    # Most Android pickers put the newest image in the first grid cell below the title bar.
    return round(width * 0.17), round(height * 0.24)


def dump_ui(adb: Path, device: str, check: bool = True) -> ET.Element | None:
    remote_xml = "/data/local/tmp/dewu_window.xml"
    dump_output = run([adb, "-s", device, "shell", "uiautomator", "dump", remote_xml], check=check)
    if "ERROR" in dump_output.upper() and not check:
        return None
    xml_text = run([adb, "-s", device, "exec-out", "cat", remote_xml], check=check)
    if "No such file" in xml_text and not check:
        return None
    if not xml_text.strip():
        return None
    try:
        return ET.fromstring(xml_text)
    except ET.ParseError:
        if check:
            raise ScriptError("Failed to parse Android UI hierarchy.")
        return None


def find_node_by_resource(root: ET.Element, hints: list[str]) -> ET.Element | None:
    lowered = [hint.lower() for hint in hints]
    for node in root.iter("node"):
        resource_id = (node.get("resource-id") or "").lower()
        if resource_id and any(hint in resource_id for hint in lowered):
            return node
    return None


def find_node_by_text(root: ET.Element, hints: list[str], exact: bool = False) -> ET.Element | None:
    for node in root.iter("node"):
        haystacks = [node.get("text") or "", node.get("content-desc") or ""]
        for haystack in haystacks:
            if not haystack:
                continue
            if exact and haystack in hints:
                return node
            if not exact and any(hint in haystack for hint in hints):
                return node
    return None


def find_picker_thumbnail(root: ET.Element) -> ET.Element | None:
    candidates = []
    for node in root.iter("node"):
        class_name = node.get("class") or ""
        bounds = node.get("bounds") or ""
        if not bounds:
            continue
        left, top, right, bottom = parse_bounds(bounds)
        width = right - left
        height = bottom - top
        resource_id = (node.get("resource-id") or "").lower()
        looks_like_image = "image" in class_name.lower() or "photo" in resource_id or "thumbnail" in resource_id
        if looks_like_image and width >= 120 and height >= 120 and top > 120:
            candidates.append((top, left, node))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


def node_center(node: ET.Element) -> tuple[int, int]:
    left, top, right, bottom = parse_bounds(node.get("bounds") or "")
    return round((left + right) / 2), round((top + bottom) / 2)


def parse_bounds(bounds: str) -> tuple[int, int, int, int]:
    cleaned = bounds.replace("][", ",").replace("[", "").replace("]", "")
    parts = [int(part) for part in cleaned.split(",")]
    if len(parts) != 4:
        raise ScriptError(f"Invalid bounds: {bounds}")
    return parts[0], parts[1], parts[2], parts[3]


def wm_size(adb: Path, device: str) -> tuple[int, int]:
    output = run([adb, "-s", device, "shell", "wm", "size"], check=False)
    for token in output.replace("Physical size:", "").split():
        if "x" in token:
            left, right = token.split("x", 1)
            if left.isdigit() and right.isdigit():
                return int(left), int(right)
    return 1440, 2560


def tap(adb: Path, device: str, x: int, y: int, label: str) -> None:
    print(f"{label}: ({x}, {y})")
    run([adb, "-s", device, "shell", "input", "tap", str(x), str(y)])


def run(command: list[object], check: bool = True) -> str:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    result = subprocess.run(
        [str(part) for part in command],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    output = f"{result.stdout}{result.stderr}"
    if check and result.returncode != 0:
        raise ScriptError(f"Command failed: {' '.join(str(part) for part in command)}\n{output}")
    return output


if __name__ == "__main__":
    raise SystemExit(main())
