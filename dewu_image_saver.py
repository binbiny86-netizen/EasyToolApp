import hashlib
import json
import os
import queue
import re
import threading
import urllib.request
import base64
import gzip
import zlib
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote, urlsplit

from mitmproxy import http
from PIL import Image

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:
    pillow_heif = None


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(min_value, min(max_value, parsed))


BASE_DIR = Path(__file__).parent
OUTPUT_ROOT = Path(os.getenv("DEWU_OUTPUT_DIR", BASE_DIR)).expanduser().resolve()
IMAGE_DIR = OUTPUT_ROOT / "images"
VIDEO_DIR = OUTPUT_ROOT / "videos"
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_DIR.mkdir(parents=True, exist_ok=True)

DEBUG_MODE = _bool_env("DEWU_DEBUG", True)
DEBUG_LOG = OUTPUT_ROOT / "dewu_requests.log"
EVENT_LOG = OUTPUT_ROOT / "capture_events.log"
PRODUCT_DEBUG_DIR = OUTPUT_ROOT / "product_debug"
JPEG_QUALITY = _int_env("DEWU_JPEG_QUALITY", 95, 1, 100)
OUTPUT_FORMAT = "JPEG"
OUTPUT_EXT = ".jpg"
SCRIPT_VERSION = "2026-05-28-product-media-v5"
PRODUCT_DEBUG_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_HOST_KEYWORDS = "dewu,poizon,shihuo,dewucdn,dewuimg,aliyuncs"
DEWU_HOST_KEYWORDS = {
    item.strip().lower()
    for item in os.getenv("DEWU_HOST_KEYWORDS", DEFAULT_HOST_KEYWORDS).split(",")
    if item.strip()
}

IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/bmp",
    "image/avif",
    "image/tiff",
    "image/heic",
    "image/heif",
    "image/x-icon",
}

IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".avif",
    ".tiff",
    ".ico",
    ".heic",
    ".heif",
}

SKIP_IMAGE_PATH_TOKENS = {"favicon.ico", "captcha", "blank.png"}
JSON_URL_RE = re.compile(r"https?:\\?/\\?/[^\s\"'<>]+", re.IGNORECASE)
downloaded_json_urls = set()
downloaded_video_keys = set()
downloaded_video_keys_lock = threading.Lock()

PRODUCT_API_TOKENS = (
    "/product/detail",
    "/product/detailv",
    "/product-search/",
    "/detail-bff/",
    "/product/layer/",
    "/shopping/ice/flow/product",
    "query-smail-image-3d360-list",
)

VIDEO_API_TOKENS = (
    "/video",
    "video-url",
    "change-video-url",
    "glide-video-guide",
    "content/glide",
    "sns-cnt-center",
    "sns-rec",
    "sns-og",
)

JSON_SKIP_URL_TOKENS = (
    ".mp3",
    ".zip",
    "captcha",
)

PRODUCT_IMAGE_URL_TOKENS = (
    "pro-img/origin-img",
    "/origin-img/",
    "/pro-img/",
    "/du_app/",
    "/product/",
    "/sku/",
    "/spu/",
    "3d/",
)

VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-flv",
    "video/webm",
    "video/3gpp",
    "video/x-matroska",
    "video/x-ms-wmv",
    "video/ogg",
    "video/mp2t",
    "video/3gpp2",
    "application/x-mpegurl",
    "application/vnd.apple.mpegurl",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".mpeg",
    ".mpg",
    ".mov",
    ".avi",
    ".flv",
    ".webm",
    ".3gp",
    ".mkv",
    ".m4v",
    ".wmv",
    ".ogv",
    ".ts",
    ".m3u8",
    ".3g2",
}

LOG_PRINT_QUEUE: "queue.Queue[str | None]" = queue.Queue(maxsize=1000)


def _stdout_log_worker():
    while True:
        line = LOG_PRINT_QUEUE.get()
        if line is None:
            return
        try:
            print(line, flush=True)
        except Exception:
            pass


threading.Thread(target=_stdout_log_worker, daemon=True).start()


def log_event(event: str, **fields):
    payload = {"event": event, **fields}
    line = json.dumps(payload, ensure_ascii=False)
    try:
        with open(EVENT_LOG, "a", encoding="utf-8") as file:
            file.write(line + "\n")
    except Exception:
        pass
    try:
        LOG_PRINT_QUEUE.put_nowait(line)
    except queue.Full:
        pass


def debug_request(content_type: str, url: str):
    if not DEBUG_MODE:
        return
    media_tokens = ("image", "video", "octet-stream")
    url_tokens = (".mp4", ".jpg", ".png", ".webp", ".mov", "video", "image")
    if any(token in content_type for token in media_tokens) or any(
        token in url.lower() for token in url_tokens
    ):
        with open(DEBUG_LOG, "a", encoding="utf-8") as file:
            file.write(f"[{content_type}] {url}\n")
        log_event("media_request", content_type=content_type, url=url)


def is_dewu_request(host: str) -> bool:
    host = host.lower()
    return any(keyword in host for keyword in DEWU_HOST_KEYWORDS)


def is_probably_json_response(flow: http.HTTPFlow) -> bool:
    content_type = flow.response.headers.get("content-type", "").lower()
    if "json" in content_type or "text/plain" in content_type:
        return True
    url = flow.request.url.lower()
    return "/api/" in url or "graphql" in url


def is_product_api_url(url: str) -> bool:
    lower = url.lower()
    return any(token in lower for token in PRODUCT_API_TOKENS)


def is_video_api_url(url: str) -> bool:
    lower = url.lower()
    return any(token in lower for token in VIDEO_API_TOKENS)


def should_skip_image_url(url: str) -> bool:
    lower = url.lower().split("?")[0]
    return any(token in lower for token in SKIP_IMAGE_PATH_TOKENS)


def should_skip_json_url(url: str) -> bool:
    lower = url.lower().split("?")[0]
    return should_skip_image_url(url) or any(token in lower for token in JSON_SKIP_URL_TOKENS)


def is_product_image_url(url: str) -> bool:
    lower = url.lower()
    return any(token in lower for token in PRODUCT_IMAGE_URL_TOKENS)


def is_video_url(url: str) -> bool:
    lower = url.lower()
    if "video/snapshot" in lower or "x-oss-process=video/snapshot" in lower:
        return True
    path = urlsplit(lower).path
    if any(path.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return False
    return (
        any(path.endswith(ext) for ext in VIDEO_EXTENSIONS)
        or "/video/" in path
        or "video-cdn" in lower
        or "/mf/" in path
    )


def restore_video_url_from_snapshot(url: str) -> str | None:
    lower = url.lower()
    if "video/snapshot" not in lower and "x-oss-process=video/snapshot" not in lower:
        return None
    return re.sub(r"([?&])x-oss-process=video/snapshot[^&]*&?", r"\1", url).rstrip("?&")


def canonical_video_key(url: str) -> str:
    restored = restore_video_url_from_snapshot(url) or url
    parsed = urlsplit(restored)
    path = parsed.path.lower()
    if path:
        return path
    return restored.split("?")[0].lower()


def is_image_response(flow: http.HTTPFlow) -> bool:
    content_type = flow.response.headers.get("content-type", "").lower()
    url_path = flow.request.url.split("?")[0].lower()

    if should_skip_image_url(flow.request.url):
        return False
    if any(content_type.startswith(ct) for ct in IMAGE_CONTENT_TYPES):
        return True
    if content_type.startswith("image/"):
        return True
    if any(url_path.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return True
    if content_type.startswith("application/octet-stream"):
        return any(token in url_path for token in ("/image/", "~tplv-", "imagex"))
    if "/image/" in url_path or "~tplv-" in url_path or "imagex" in url_path:
        return True
    return False


def is_video_response(flow: http.HTTPFlow) -> bool:
    content_type = flow.response.headers.get("content-type", "").lower()
    url = flow.request.url.lower()

    if "video/snapshot" in url or "x-oss-process=video/snapshot" in url:
        return False
    if any(content_type.startswith(ct) for ct in VIDEO_CONTENT_TYPES):
        return True
    if content_type.startswith("video/"):
        return True
    if content_type.startswith("image/"):
        return False

    url_path = url.split("?")[0]
    if any(url_path.endswith(ext) for ext in VIDEO_EXTENSIONS):
        return True
    if "/video/" in url_path or "video-cdn" in url:
        return True
    return False


def convert_to_rgb_jpeg(raw_bytes: bytes) -> bytes:
    img = Image.open(BytesIO(raw_bytes))
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode == "P":
        if "transparency" in img.info:
            img = img.convert("RGBA")
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[3])
            img = bg
        else:
            img = img.convert("RGB")
    elif img.mode != "RGB" and img.mode != "CMYK":
        img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, format=OUTPUT_FORMAT, quality=JPEG_QUALITY)
    return buf.getvalue()


def save_image_bytes(raw_bytes: bytes, source_url: str, source: str):
    try:
        jpeg_data = convert_to_rgb_jpeg(raw_bytes)
    except Exception as error:
        log_event("convert_failed", error=str(error), url=source_url, source=source)
        return

    url_hash = hashlib.md5(source_url.encode()).hexdigest()[:12]
    filename = f"{url_hash}{OUTPUT_EXT}"
    filepath = IMAGE_DIR / filename

    if filepath.exists():
        log_event("image_duplicate", file=filename, url_hash=url_hash, source=source)
        return

    with open(filepath, "wb") as file:
        file.write(jpeg_data)

    log_event(
        "image_saved",
        file=filename,
        bytes=len(jpeg_data),
        url_hash=url_hash,
        source=source,
        url=source_url,
    )


def save_image(flow: http.HTTPFlow):
    log_event(
        "image_detected",
        content_type=flow.response.headers.get("content-type", ""),
        bytes=len(flow.response.content),
        url=flow.request.url,
    )
    restored_video_url = restore_video_url_from_snapshot(flow.request.url)
    if restored_video_url:
        threading.Thread(
            target=save_json_embedded_video,
            args=(restored_video_url, flow.request.url),
            daemon=True,
        ).start()
    save_image_bytes(flow.response.content, flow.request.url, "response")


def extract_image_urls_from_text(text: str) -> list[str]:
    urls = set()
    normalized = text.replace("\\/", "/")
    for match in JSON_URL_RE.finditer(normalized):
        url = unquote(match.group(0).rstrip("\\,.;)}]"))
        if is_dewu_request(url) and not should_skip_json_url(url) and not is_video_url(url):
            urls.add(url)
    return sorted(urls)


def extract_video_urls_from_text(text: str) -> list[str]:
    urls = set()
    normalized = text.replace("\\/", "/")
    for match in JSON_URL_RE.finditer(normalized):
        url = unquote(match.group(0).rstrip("\\,.;)}]"))
        if is_dewu_request(url) and not should_skip_json_url(url) and is_video_url(url):
            urls.add(restore_video_url_from_snapshot(url) or url)
    return sorted(urls)


def decode_possible_data_payload(value: str) -> list[tuple[str, str]]:
    if not value or len(value) < 40:
        return []

    payload = value.strip()
    padding = "=" * ((4 - len(payload) % 4) % 4)
    decoded_texts = []
    try:
        raw = base64.urlsafe_b64decode((payload + padding).encode("ascii"))
    except Exception:
        return []

    candidates = [("base64url", raw)]
    for name, decoder in (
        ("gzip", gzip.decompress),
        ("zlib", zlib.decompress),
        ("deflate", lambda data: zlib.decompress(data, -zlib.MAX_WBITS)),
    ):
        try:
            candidates.append((name, decoder(raw)))
        except Exception:
            pass

    for name, data in candidates:
        for encoding in ("utf-8", "utf-16", "gb18030"):
            try:
                text = data.decode(encoding)
            except Exception:
                continue
            if "http" in text or "image" in text or "product" in text:
                decoded_texts.append((f"{name}:{encoding}", text))
                break
    return decoded_texts


def extract_urls_from_json_payload(text: str) -> list[str]:
    urls = set(extract_image_urls_from_text(text))
    try:
        payload = json.loads(text)
    except Exception:
        return sorted(urls)

    def walk(value):
        if isinstance(value, str):
            for _, decoded_text in decode_possible_data_payload(value):
                urls.update(extract_image_urls_from_text(decoded_text))
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(payload)
    return sorted(urls)


def extract_video_urls_from_json_payload(text: str) -> list[str]:
    urls = set(extract_video_urls_from_text(text))
    try:
        payload = json.loads(text)
    except Exception:
        return sorted(urls)

    def walk(value):
        if isinstance(value, str):
            for _, decoded_text in decode_possible_data_payload(value):
                urls.update(extract_video_urls_from_text(decoded_text))
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, dict):
            for item in value.values():
                walk(item)

    walk(payload)
    return sorted(urls)


def dump_product_response(flow: http.HTTPFlow, text: str):
    if not is_product_api_url(flow.request.url):
        return

    url_hash = hashlib.md5(flow.request.url.encode()).hexdigest()[:12]
    filepath = PRODUCT_DEBUG_DIR / f"{url_hash}.json"
    try:
        request_text = flow.request.get_text(strict=False)
    except Exception:
        request_text = ""

    decoded_payloads = []
    try:
        payload = json.loads(text)
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, str):
            for method, decoded_text in decode_possible_data_payload(data):
                decoded_payloads.append(
                    {
                        "method": method,
                        "sample": decoded_text[:5000],
                        "urls": extract_image_urls_from_text(decoded_text)[:50],
                    }
                )
    except Exception:
        pass

    record = {
        "url": flow.request.url,
        "method": flow.request.method,
        "request": request_text,
        "response": text,
        "decodedPayloads": decoded_payloads,
    }
    try:
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(record, file, ensure_ascii=False, indent=2)
        log_event(
            "product_response_dumped",
            file=str(filepath),
            bytes=len(flow.response.content),
            decoded_payloads=len(decoded_payloads),
            url=flow.request.url,
        )
    except Exception as error:
        log_event("product_response_dump_failed", error=str(error), url=flow.request.url)


def save_json_embedded_image(url: str, source_url: str):
    if url in downloaded_json_urls:
        log_event("json_image_duplicate_url", url=url)
        return
    downloaded_json_urls.add(url)
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            },
        )
        with urllib.request.urlopen(request, timeout=12) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read()
        if not content_type.lower().startswith("image/"):
            log_event(
                "json_url_not_image",
                content_type=content_type,
                bytes=len(raw),
                url=url,
                source_url=source_url,
            )
            return
        log_event(
            "json_image_downloaded",
            content_type=content_type,
            bytes=len(raw),
            url=url,
            source_url=source_url,
        )
        save_image_bytes(raw, url, "product_json" if is_product_api_url(source_url) else "json")
    except Exception as error:
        log_event("json_image_failed", error=str(error), url=url, source_url=source_url)


def video_extension_from_url(url: str, content_type: str) -> str:
    content_type = content_type.lower()
    url_path = url.split("?")[0].lower()
    mapping = [
        (".mov", "video/quicktime"),
        (".webm", "video/webm"),
        (".flv", "video/x-flv"),
        (".avi", "video/x-msvideo"),
        (".mkv", "video/x-matroska"),
        (".m3u8", "mpegurl"),
        (".ts", "video/mp2t"),
    ]
    for ext, token in mapping:
        if token in content_type or url_path.endswith(ext):
            return ext
    for ext in VIDEO_EXTENSIONS:
        if url_path.endswith(ext):
            return ext
    return ".mp4"


def save_video_bytes(raw_bytes: bytes, source_url: str, source: str, content_type: str):
    storage_key = canonical_video_key(source_url)
    url_hash = hashlib.md5(storage_key.encode()).hexdigest()[:12]
    filename = f"{url_hash}{video_extension_from_url(source_url, content_type)}"
    filepath = VIDEO_DIR / filename
    temp_path = VIDEO_DIR / f"{filename}.{os.getpid()}.{threading.get_ident()}.downloading"

    if filepath.exists():
        log_event(
            "video_duplicate",
            file=filename,
            url_hash=url_hash,
            source=source,
            existing_bytes=filepath.stat().st_size,
            bytes=len(raw_bytes),
            key=storage_key,
        )
        return

    try:
        with open(temp_path, "wb") as file:
            file.write(raw_bytes)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp_path, filepath)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    log_event(
        "video_saved",
        file=filename,
        bytes=len(raw_bytes),
        url_hash=url_hash,
        source=source,
        url=source_url,
        key=storage_key,
    )


def content_range_total(content_range: str) -> int | None:
    match = re.search(r"/(\d+)\s*$", content_range or "")
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def is_partial_video_response(status_code: int, headers, body_size: int) -> bool:
    content_range = headers.get("content-range", "") or headers.get("Content-Range", "")
    total = content_range_total(content_range)
    return status_code == 206 or (total is not None and body_size < total)


def download_video_url(url: str, source_url: str, source: str):
    url = restore_video_url_from_snapshot(url) or url
    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "video/*,application/vnd.apple.mpegurl,application/x-mpegurl,*/*;q=0.8",
                "Connection": "close",
            },
        )
        with urllib.request.urlopen(request, timeout=90) as response:
            content_type = response.headers.get("content-type", "")
            content_range = response.headers.get("content-range", "")
            raw = response.read()
            status = getattr(response, "status", 200)

        if not (
            content_type.lower().startswith("video/")
            or "mpegurl" in content_type.lower()
            or is_video_url(url)
        ):
            log_event(
                "json_url_not_video",
                content_type=content_type,
                bytes=len(raw),
                url=url,
                source_url=source_url,
            )
            return False

        total = content_range_total(content_range)
        if status == 206 or (total is not None and len(raw) < total):
            log_event(
                "video_partial_downloaded",
                status=status,
                content_type=content_type,
                bytes=len(raw),
                total=total,
                url=url,
                source_url=source_url,
            )
            return False
        else:
            log_event(
                "json_video_downloaded",
                status=status,
                content_type=content_type,
                bytes=len(raw),
                content_range=content_range,
                url=url,
                source_url=source_url,
            )

        save_video_bytes(raw, url, source, content_type)
        return True
    except Exception as error:
        log_event("json_video_failed", error=str(error), url=url, source_url=source_url)
        return False


def download_claimed_video_url(url: str, source_url: str, source: str, key: str):
    if download_video_url(url, source_url, source):
        return
    with downloaded_video_keys_lock:
        downloaded_video_keys.discard(key)


def save_json_embedded_video(url: str, source_url: str):
    key = canonical_video_key(url)
    with downloaded_video_keys_lock:
        if key in downloaded_video_keys:
            log_event("json_video_duplicate_url", url=url, key=key)
            return
        downloaded_video_keys.add(key)
    download_claimed_video_url(url, source_url, "product_json", key)


def handle_json_images(flow: http.HTTPFlow):
    if not is_probably_json_response(flow):
        return
    product_api = is_product_api_url(flow.request.url)
    video_api = is_video_api_url(flow.request.url)
    if not product_api and not video_api:
        return
    try:
        text = flow.response.get_text(strict=False)
    except Exception as error:
        log_event("json_read_failed", error=str(error), url=flow.request.url)
        return

    dump_product_response(flow, text)
    urls = extract_urls_from_json_payload(text)
    video_urls = extract_video_urls_from_json_payload(text)
    product_urls = [url for url in urls if is_product_image_url(url)]
    if product_urls:
        urls = product_urls
    if not urls and not video_urls:
        log_event(
            "json_no_urls_found",
            content_type=flow.response.headers.get("content-type", ""),
            bytes=len(flow.response.content),
            url=flow.request.url,
            sample=text[:500],
        )
        return
    if urls:
        log_event("json_image_urls_found", count=len(urls), sample=urls[:5], url=flow.request.url)
    for url in urls[:80]:
        threading.Thread(
            target=save_json_embedded_image,
            args=(url, flow.request.url),
            daemon=True,
        ).start()
    if video_urls:
        log_event(
            "json_video_urls_found",
            count=len(video_urls),
            sample=video_urls[:5],
            url=flow.request.url,
        )
    for url in video_urls[:30]:
        threading.Thread(
            target=save_json_embedded_video,
            args=(url, flow.request.url),
            daemon=True,
        ).start()


def video_extension(flow: http.HTTPFlow) -> str:
    content_type = flow.response.headers.get("content-type", "").lower()
    url_path = flow.request.url.split("?")[0].lower()
    mapping = [
        (".mov", "video/quicktime"),
        (".webm", "video/webm"),
        (".flv", "video/x-flv"),
        (".avi", "video/x-msvideo"),
        (".mkv", "video/x-matroska"),
        (".m3u8", "mpegurl"),
        (".ts", "video/mp2t"),
    ]
    for ext, token in mapping:
        if token in content_type or url_path.endswith(ext):
            return ext
    for ext in VIDEO_EXTENSIONS:
        if url_path.endswith(ext):
            return ext
    return ".mp4"


def save_video(flow: http.HTTPFlow):
    status_code = getattr(flow.response, "status_code", 200)
    content_range = flow.response.headers.get("content-range", "") or flow.response.headers.get(
        "Content-Range", ""
    )
    log_event(
        "video_detected",
        status=status_code,
        content_type=flow.response.headers.get("content-type", ""),
        bytes=len(flow.response.content),
        content_range=content_range,
        url=flow.request.url,
    )
    if is_partial_video_response(status_code, flow.response.headers, len(flow.response.content)):
        key = canonical_video_key(flow.request.url)
        with downloaded_video_keys_lock:
            should_download = key not in downloaded_video_keys
            if should_download:
                downloaded_video_keys.add(key)
        log_event(
            "video_partial_response_skipped",
            status=status_code,
            content_type=flow.response.headers.get("content-type", ""),
            bytes=len(flow.response.content),
            content_range=content_range,
            full_download=should_download,
            url=flow.request.url,
            key=key,
        )
        if should_download:
            threading.Thread(
                target=download_claimed_video_url,
                args=(flow.request.url, flow.request.url, "response_full", key),
                daemon=True,
            ).start()
        return
    save_video_bytes(
        flow.response.content,
        flow.request.url,
        "response",
        flow.response.headers.get("content-type", ""),
    )


class DewuImageSaver:
    def load(self, loader):
        log_event(
            "sidecar_loaded",
            output_root=str(OUTPUT_ROOT),
            debug=DEBUG_MODE,
            jpeg_quality=JPEG_QUALITY,
            host_keywords=sorted(DEWU_HOST_KEYWORDS),
            heif_enabled=pillow_heif is not None,
            script_version=SCRIPT_VERSION,
        )

    def response(self, flow: http.HTTPFlow):
        try:
            if not flow.response or not flow.response.content:
                return
            if not is_dewu_request(flow.request.host):
                return

            content_type = flow.response.headers.get("content-type", "").lower()
            debug_request(content_type, flow.request.url)
            handle_json_images(flow)

            image_match = is_image_response(flow)
            video_match = is_video_response(flow)
            if image_match or video_match:
                log_event(
                    "response_classified",
                    content_type=content_type,
                    bytes=len(flow.response.content),
                    image=image_match,
                    video=video_match,
                    url=flow.request.url,
                )

            if image_match:
                save_image(flow)
            elif video_match:
                save_video(flow)
        except Exception as error:
            log_event("response_failed", error=str(error), url=flow.request.url)


addons = [DewuImageSaver()]
