use base64::{engine::general_purpose, Engine as _};
use reqwest::blocking::multipart::{Form, Part};
use serde::{Deserialize, Serialize};
use std::{
    env, fs,
    io::{BufRead, BufReader},
    net::{IpAddr, TcpListener, TcpStream, ToSocketAddrs, UdpSocket},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    thread,
    time::{Duration, SystemTime},
};
use tauri::{path::BaseDirectory, AppHandle, Emitter, Manager, State};

struct CaptureProcess {
    child: Child,
}

#[derive(Default)]
struct CaptureState {
    process: Mutex<Option<CaptureProcess>>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CaptureConfig {
    port: u16,
    output_root: String,
    debug_mode: bool,
    jpeg_quality: u8,
    host_keywords: Vec<String>,
    mitmdump_command: Option<String>,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct CaptureStatus {
    running: bool,
}

#[derive(Debug, Serialize, Clone)]
#[serde(rename_all = "camelCase")]
struct LogLine {
    stream: String,
    line: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct MediaFile {
    name: String,
    path: String,
    kind: String,
    bytes: u64,
    modified_ms: u128,
    width: Option<u32>,
    height: Option<u32>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct MediaList {
    images: Vec<MediaFile>,
    videos: Vec<MediaFile>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AdbInfo {
    adb_path: Option<String>,
    devices: Vec<String>,
    candidate_ports: Vec<u16>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
struct AdbProxyResult {
    adb_path: String,
    device: String,
    proxy: String,
    output: String,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct EasyToolLoginData {
    id: Option<u64>,
    username: Option<String>,
    display_name: Option<String>,
    menu_permissions: Option<Vec<String>>,
    token: String,
    expires_at: Option<String>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct EasyToolImageAsset {
    original_path: Option<String>,
    preview_path: Option<String>,
    storage_type: Option<String>,
    original_url: Option<String>,
    preview_url: Option<String>,
    original_width: Option<u32>,
    original_height: Option<u32>,
    preview_width: Option<u32>,
    preview_height: Option<u32>,
    size: Option<u64>,
}

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
struct EasyToolUploadData {
    product_id: u64,
    ai_reference_images: Vec<EasyToolImageAsset>,
    uploaded_images: Vec<EasyToolImageAsset>,
    video: Option<String>,
    added_image_count: Option<u32>,
    video_updated: Option<bool>,
}

#[derive(Debug, Deserialize)]
struct EasyToolApiResponse<T> {
    code: i32,
    message: Option<String>,
    data: Option<T>,
}

#[tauri::command]
fn get_capture_status(state: State<CaptureState>) -> Result<CaptureStatus, String> {
    let mut guard = state
        .process
        .lock()
        .map_err(|_| "capture state lock failed")?;
    if let Some(process) = guard.as_mut() {
        match process.child.try_wait() {
            Ok(Some(_)) => {
                *guard = None;
                Ok(CaptureStatus { running: false })
            }
            Ok(None) => Ok(CaptureStatus { running: true }),
            Err(error) => Err(format!("failed to inspect capture process: {error}")),
        }
    } else {
        Ok(CaptureStatus { running: false })
    }
}

#[tauri::command]
fn start_capture(
    app: AppHandle,
    state: State<CaptureState>,
    config: CaptureConfig,
) -> Result<CaptureStatus, String> {
    let mut guard = state
        .process
        .lock()
        .map_err(|_| "capture state lock failed")?;
    if guard.is_some() {
        return Ok(CaptureStatus { running: true });
    }
    if let Some(cleanup_log) = ensure_capture_port_available(config.port)? {
        let _ = app.emit(
            "capture-log",
            LogLine {
                stream: "app".to_string(),
                line: cleanup_log,
            },
        );
    }

    let script_path = sidecar_script_path(&app)?;
    let output_root = resolve_output_root(&app, &config.output_root)?;
    fs::create_dir_all(output_root.join("images"))
        .map_err(|error| format!("failed to create images directory: {error}"))?;
    fs::create_dir_all(output_root.join("videos"))
        .map_err(|error| format!("failed to create videos directory: {error}"))?;

    let command_line = config
        .mitmdump_command
        .as_deref()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or("mitmdump");
    let (program, pre_args) = split_command_line(command_line)?;
    let program = resolve_mitmdump_program(&program);

    let mut command = Command::new(program);
    command
        .args(pre_args)
        .arg("-s")
        .arg(script_path)
        .arg("-p")
        .arg(config.port.to_string())
        .env("DEWU_OUTPUT_DIR", output_root.to_string_lossy().to_string())
        .env("DEWU_DEBUG", if config.debug_mode { "1" } else { "0" })
        .env("DEWU_JPEG_QUALITY", config.jpeg_quality.to_string())
        .env("DEWU_HOST_KEYWORDS", config.host_keywords.join(","))
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = command
        .spawn()
        .map_err(|error| format!("failed to start mitmdump: {error}"))?;

    thread::sleep(Duration::from_millis(700));
    if let Ok(Some(status)) = child.try_wait() {
        return Err(format!(
            "mitmdump exited immediately with status {status}. Check command `{command_line}` and port {}.",
            config.port
        ));
    }

    if let Some(stdout) = child.stdout.take() {
        stream_process_output(app.clone(), "stdout", stdout);
    }
    if let Some(stderr) = child.stderr.take() {
        stream_process_output(app, "stderr", stderr);
    }

    *guard = Some(CaptureProcess { child });
    Ok(CaptureStatus { running: true })
}

#[tauri::command]
fn stop_capture(state: State<CaptureState>) -> Result<CaptureStatus, String> {
    let mut guard = state
        .process
        .lock()
        .map_err(|_| "capture state lock failed")?;
    if let Some(mut process) = guard.take() {
        process
            .child
            .kill()
            .map_err(|error| format!("failed to stop capture process: {error}"))?;
        let _ = process.child.wait();
    }
    Ok(CaptureStatus { running: false })
}

#[tauri::command]
fn get_local_ips() -> Vec<String> {
    let mut ips = Vec::new();
    if let Ok(socket) = UdpSocket::bind("0.0.0.0:0") {
        if socket.connect("8.8.8.8:80").is_ok() {
            if let Ok(local_addr) = socket.local_addr() {
                if let IpAddr::V4(ip) = local_addr.ip() {
                    ips.push(ip.to_string());
                }
            }
        }
    }
    if !ips.iter().any(|ip| ip == "127.0.0.1") {
        ips.push("127.0.0.1".to_string());
    }
    ips
}

#[tauri::command]
fn list_media(app: AppHandle, output_root: String) -> Result<MediaList, String> {
    let root = resolve_output_root(&app, &output_root)?;
    let mut images = read_media_dir(&root.join("images"), "image")?;
    let mut videos = read_media_dir(&root.join("videos"), "video")?;
    images.sort_by(|a, b| b.modified_ms.cmp(&a.modified_ms));
    videos.sort_by(|a, b| b.modified_ms.cmp(&a.modified_ms));
    Ok(MediaList { images, videos })
}

#[tauri::command]
fn delete_file(path: String) -> Result<(), String> {
    fs::remove_file(path).map_err(|error| format!("failed to delete file: {error}"))
}

#[tauri::command]
fn read_media_data_url(path: String) -> Result<String, String> {
    let path = PathBuf::from(path);
    let bytes = fs::read(&path).map_err(|error| format!("failed to read media file: {error}"))?;
    let mime = match path
        .extension()
        .and_then(|ext| ext.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "jpg" | "jpeg" => "image/jpeg",
        "png" => "image/png",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "mp4" | "m4v" => "video/mp4",
        "webm" => "video/webm",
        "mov" => "video/quicktime",
        "ogv" | "ogg" => "video/ogg",
        "mkv" => "video/x-matroska",
        "avi" => "video/x-msvideo",
        _ => "application/octet-stream",
    };
    Ok(format!(
        "data:{mime};base64,{}",
        general_purpose::STANDARD.encode(bytes)
    ))
}

#[tauri::command]
fn clear_media(app: AppHandle, output_root: String, kind: String) -> Result<(), String> {
    let output_root = resolve_output_root(&app, &output_root)?;
    let folder = match kind.as_str() {
        "image" => "images",
        "video" => "videos",
        "all" => "",
        _ => return Err("unknown media kind".to_string()),
    };

    if kind == "all" {
        clear_folder(output_root.join("images"))?;
        clear_folder(output_root.join("videos"))?;
    } else {
        clear_folder(output_root.join(folder))?;
    }
    Ok(())
}

#[tauri::command]
fn open_path(path: String) -> Result<(), String> {
    #[cfg(target_os = "windows")]
    let mut command = {
        let mut command = Command::new("explorer");
        command.arg(path);
        command
    };

    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("open");
        command.arg(path);
        command
    };

    #[cfg(target_os = "linux")]
    let mut command = {
        let mut command = Command::new("xdg-open");
        command.arg(path);
        command
    };

    command
        .spawn()
        .map_err(|error| format!("failed to open path: {error}"))?;
    Ok(())
}

fn split_command_line(command_line: &str) -> Result<(String, Vec<String>), String> {
    let parts: Vec<String> = command_line
        .split_whitespace()
        .map(|part| part.to_string())
        .collect();
    let Some(program) = parts.first() else {
        return Err("mitmdump command is empty".to_string());
    };
    Ok((program.clone(), parts.into_iter().skip(1).collect()))
}

fn resolve_mitmdump_program(program: &str) -> String {
    if program.eq_ignore_ascii_case("mitmdump") || program.eq_ignore_ascii_case("mitmdump.exe") {
        if let Some(path) = python_scripts_mitmdump() {
            return path.to_string_lossy().to_string();
        }
    }
    program.to_string()
}

fn python_scripts_mitmdump() -> Option<PathBuf> {
    let code = r#"import pathlib, sysconfig
name = "mitmdump.exe" if __import__("os").name == "nt" else "mitmdump"
print(pathlib.Path(sysconfig.get_path("scripts")) / name)
"#;
    for python in python_launchers() {
        let Ok(output) = Command::new(python).args(["-c", code]).output() else {
            continue;
        };
        if !output.status.success() {
            continue;
        }
        let stdout = String::from_utf8_lossy(&output.stdout);
        let path = PathBuf::from(stdout.trim());
        if path.exists() {
            return Some(path);
        }
    }

    common_mitmdump_paths()
        .into_iter()
        .find(|path| path.exists())
}

#[cfg(target_os = "windows")]
fn python_launchers() -> Vec<&'static str> {
    vec!["py", "python", "python3"]
}

#[cfg(not(target_os = "windows"))]
fn python_launchers() -> Vec<&'static str> {
    vec!["python3", "python"]
}

fn common_mitmdump_paths() -> Vec<PathBuf> {
    let mut paths = Vec::new();

    #[cfg(target_os = "macos")]
    {
        paths.push(PathBuf::from("/opt/homebrew/bin/mitmdump"));
        paths.push(PathBuf::from("/usr/local/bin/mitmdump"));
    }

    #[cfg(target_os = "linux")]
    {
        paths.push(PathBuf::from("/usr/bin/mitmdump"));
        paths.push(PathBuf::from("/usr/local/bin/mitmdump"));
    }

    if let Ok(home) = env::var("HOME") {
        paths.push(
            PathBuf::from(home)
                .join(".local")
                .join("bin")
                .join("mitmdump"),
        );
    }

    paths
}

fn ensure_port_available(port: u16) -> Result<(), String> {
    TcpListener::bind(("0.0.0.0", port))
        .map(|_| ())
        .map_err(|error| {
            format!(
                "port {port} is already in use. Choose another listening port before starting capture. {error}"
            )
        })
}

fn ensure_capture_port_available(port: u16) -> Result<Option<String>, String> {
    match ensure_port_available(port) {
        Ok(()) => Ok(None),
        Err(first_error) => {
            let cleanup_log = cleanup_stale_capture_processes(port)?;
            if cleanup_log.is_none() {
                return Err(first_error);
            }

            thread::sleep(Duration::from_millis(900));
            ensure_port_available(port).map_err(|error| {
                format!(
                    "{error}\nTried to close the previous Dewu capture process on port {port}, but the port is still busy."
                )
            })?;
            Ok(cleanup_log)
        }
    }
}

#[cfg(target_os = "windows")]
fn cleanup_stale_capture_processes(port: u16) -> Result<Option<String>, String> {
    let script = format!(
        r#"
$ErrorActionPreference = 'SilentlyContinue'
$port = {port}
$regex = "(^|\s)-p\s+$port(\s|$)"
$targets = @(Get-CimInstance Win32_Process | Where-Object {{
  $_.ProcessId -ne $PID -and
  $_.CommandLine -match 'dewu_image_saver\.py' -and
  $_.CommandLine -match $regex
}})
if ($targets.Count -eq 0) {{
  exit 0
}}
foreach ($target in $targets) {{
  Stop-Process -Id $target.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Output ("closed stale capture process pid=" + $target.ProcessId + " name=" + $target.Name)
}}
"#
    );
    let output = Command::new("powershell")
        .args([
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            &script,
        ])
        .output()
        .map_err(|error| format!("failed to inspect stale capture process: {error}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if !output.status.success() {
        return Err(format!(
            "failed to close stale capture process: {stdout}\n{stderr}"
        ));
    }
    let combined = [stdout, stderr]
        .into_iter()
        .filter(|value| !value.is_empty())
        .collect::<Vec<_>>()
        .join("\n");
    if combined.is_empty() {
        Ok(None)
    } else {
        Ok(Some(combined))
    }
}

#[cfg(not(target_os = "windows"))]
fn cleanup_stale_capture_processes(port: u16) -> Result<Option<String>, String> {
    let script = format!(
        r#"
port="{port}"
ps -axo pid=,command= | while IFS= read -r line; do
  pid="$(printf "%s\n" "$line" | awk '{{print $1}}')"
  command="$(printf "%s\n" "$line" | sed 's/^[[:space:]]*[0-9][0-9]*[[:space:]]*//')"
  case "$command" in
    *dewu_image_saver.py*"-p $port"*|*dewu_image_saver.py*"-p=$port"*)
      if [ "$pid" != "$$" ]; then
        kill "$pid" 2>/dev/null || true
        printf "closed stale capture process pid=%s\n" "$pid"
      fi
      ;;
  esac
done
"#
    );
    let output = Command::new("sh")
        .args(["-c", &script])
        .output()
        .map_err(|error| format!("failed to inspect stale capture process: {error}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
    if !output.status.success() {
        return Err(format!(
            "failed to close stale capture process: {stdout}\n{stderr}"
        ));
    }
    let combined = [stdout, stderr]
        .into_iter()
        .filter(|value| !value.is_empty())
        .collect::<Vec<_>>()
        .join("\n");
    if combined.is_empty() {
        Ok(None)
    } else {
        Ok(Some(combined))
    }
}

#[tauri::command]
fn detect_mumu_adb(adb_path: Option<String>) -> Result<AdbInfo, String> {
    let adb_path = adb_path
        .filter(|path| !path.trim().is_empty())
        .and_then(|path| {
            let path = PathBuf::from(path);
            path.exists().then_some(path)
        })
        .or_else(|| find_mumu_adb().ok());
    let devices = if let Some(path) = adb_path.as_ref() {
        adb_devices(path).unwrap_or_default()
    } else {
        Vec::new()
    };

    Ok(AdbInfo {
        adb_path: adb_path.map(|path| path.to_string_lossy().to_string()),
        devices,
        candidate_ports: mumu_adb_ports(),
    })
}

#[tauri::command]
fn set_mumu_wifi_proxy(
    proxy_host: String,
    proxy_port: u16,
    adb_path: Option<String>,
) -> Result<AdbProxyResult, String> {
    if proxy_host.trim().is_empty() {
        return Err("proxy host is empty".to_string());
    }
    ensure_proxy_target_is_valid(proxy_host.trim(), proxy_port)?;

    let adb = resolve_adb(adb_path)?;
    let device = connect_mumu_device(&adb)?;
    let proxy = format!("{}:{}", proxy_host.trim(), proxy_port);

    let output = run_adb(
        &adb,
        &[
            "-s",
            &device,
            "shell",
            "settings",
            "put",
            "global",
            "http_proxy",
            &proxy,
        ],
    )?;
    let current = run_adb(
        &adb,
        &[
            "-s",
            &device,
            "shell",
            "settings",
            "get",
            "global",
            "http_proxy",
        ],
    )
    .unwrap_or_default();

    Ok(AdbProxyResult {
        adb_path: adb.to_string_lossy().to_string(),
        device,
        proxy,
        output: format!("{output}\ncurrent={}", current.trim()),
    })
}

#[tauri::command]
fn clear_mumu_wifi_proxy(adb_path: Option<String>) -> Result<AdbProxyResult, String> {
    let adb = resolve_adb(adb_path)?;
    let device = connect_mumu_device(&adb)?;

    let output = run_adb(
        &adb,
        &[
            "-s",
            &device,
            "shell",
            "settings",
            "put",
            "global",
            "http_proxy",
            ":0",
        ],
    )?;
    let _ = run_adb(
        &adb,
        &[
            "-s",
            &device,
            "shell",
            "settings",
            "delete",
            "global",
            "http_proxy",
        ],
    );

    Ok(AdbProxyResult {
        adb_path: adb.to_string_lossy().to_string(),
        device,
        proxy: ":0".to_string(),
        output,
    })
}

#[tauri::command]
fn easytool_login(
    base_url: String,
    username: String,
    password: String,
) -> Result<EasyToolLoginData, String> {
    let base_url = normalize_easytool_base_url(&base_url)?;
    let username = username.trim();
    if username.is_empty() {
        return Err("EasyTool username is empty".to_string());
    }
    if password.is_empty() {
        return Err("EasyTool password is empty".to_string());
    }

    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|error| format!("failed to create EasyTool client: {error}"))?;
    let response = client
        .post(format!("{base_url}/api/auth/login"))
        .json(&serde_json::json!({
            "username": username,
            "password": password,
        }))
        .send()
        .map_err(|error| format!("EasyTool login request failed: {error}"))?;

    parse_easytool_response(response, "EasyTool login failed")
}

#[tauri::command]
fn easytool_upload_personal_media(
    base_url: String,
    token: String,
    product_id: u64,
    image_paths: Vec<String>,
    video_path: Option<String>,
) -> Result<EasyToolUploadData, String> {
    let base_url = normalize_easytool_base_url(&base_url)?;
    let token = token.trim();
    if token.is_empty() {
        return Err("EasyTool token is empty. Login first.".to_string());
    }
    if product_id == 0 {
        return Err("EasyTool personal product ID is empty".to_string());
    }

    let video_path = video_path.and_then(|path| {
        let trimmed = path.trim().to_string();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed)
        }
    });
    if image_paths.is_empty() && video_path.is_none() {
        return Err("Select images or a video before uploading".to_string());
    }

    let mut form = Form::new();
    for image_path in image_paths {
        form = form.part("images", file_part(&image_path)?);
    }
    if let Some(path) = video_path {
        form = form.part("video", file_part(&path)?);
    }

    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(180))
        .build()
        .map_err(|error| format!("failed to create EasyTool client: {error}"))?;
    let response = client
        .post(format!(
            "{base_url}/api/dewu/personal-products/{product_id}/media"
        ))
        .bearer_auth(token)
        .multipart(form)
        .send()
        .map_err(|error| format!("EasyTool upload request failed: {error}"))?;

    parse_easytool_response(response, "EasyTool media upload failed")
}

fn stream_process_output<R>(app: AppHandle, stream: &'static str, reader: R)
where
    R: std::io::Read + Send + 'static,
{
    thread::spawn(move || {
        let reader = BufReader::new(reader);
        for line in reader.lines().map_while(Result::ok) {
            let _ = app.emit(
                "capture-log",
                LogLine {
                    stream: stream.to_string(),
                    line,
                },
            );
        }
    });
}

fn sidecar_script_path(app: &AppHandle) -> Result<PathBuf, String> {
    let cwd = std::env::current_dir().map_err(|error| format!("failed to read cwd: {error}"))?;
    let mut candidates = vec![
        cwd.join("dewu_image_saver.py"),
        cwd.parent()
            .map(|parent| parent.join("dewu_image_saver.py"))
            .unwrap_or_else(|| cwd.join("dewu_image_saver.py")),
    ];
    if let Ok(resource_path) = app
        .path()
        .resolve("dewu_image_saver.py", BaseDirectory::Resource)
    {
        candidates.push(resource_path);
    }

    candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| "dewu_image_saver.py was not found".to_string())
}

fn resolve_output_root(app: &AppHandle, output_root: &str) -> Result<PathBuf, String> {
    let value = output_root.trim();
    let path = if value.is_empty() || value == "." {
        default_output_root(app)?
    } else {
        PathBuf::from(value)
    };
    Ok(path.canonicalize().unwrap_or(path))
}

fn default_output_root(app: &AppHandle) -> Result<PathBuf, String> {
    let cwd = std::env::current_dir().map_err(|error| format!("failed to read cwd: {error}"))?;
    for candidate in [
        cwd.join("dewu_image_saver.py"),
        cwd.parent()
            .map(|parent| parent.join("dewu_image_saver.py"))
            .unwrap_or_else(|| cwd.join("dewu_image_saver.py")),
    ] {
        if candidate.exists() {
            return candidate
                .parent()
                .map(Path::to_path_buf)
                .ok_or_else(|| "failed to resolve output directory".to_string());
        }
    }
    app.path()
        .app_data_dir()
        .map_err(|error| format!("failed to resolve app data directory: {error}"))
}

fn read_media_dir(path: &Path, kind: &str) -> Result<Vec<MediaFile>, String> {
    if !path.exists() {
        return Ok(Vec::new());
    }

    let mut files = Vec::new();
    for entry in fs::read_dir(path).map_err(|error| format!("failed to read media dir: {error}"))? {
        let entry = entry.map_err(|error| format!("failed to read media entry: {error}"))?;
        let metadata = entry
            .metadata()
            .map_err(|error| format!("failed to read media metadata: {error}"))?;
        if !metadata.is_file() {
            continue;
        }
        let file_name = entry.file_name().to_string_lossy().to_string();
        if kind == "video" && is_unfinished_video_file(&file_name) {
            continue;
        }
        if kind == "video" && !is_probably_video_file(&entry.path()) {
            continue;
        }
        let modified_ms = metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(SystemTime::UNIX_EPOCH).ok())
            .map(|duration| duration.as_millis())
            .unwrap_or(0);
        let dimensions = if kind == "image" {
            read_image_dimensions(&entry.path())
        } else {
            None
        };
        files.push(MediaFile {
            name: file_name,
            path: entry.path().to_string_lossy().to_string(),
            kind: kind.to_string(),
            bytes: metadata.len(),
            modified_ms,
            width: dimensions.map(|(width, _)| width),
            height: dimensions.map(|(_, height)| height),
        });
    }
    Ok(files)
}

fn is_unfinished_video_file(file_name: &str) -> bool {
    let lower = file_name.to_ascii_lowercase();
    lower.ends_with(".downloading") || lower.ends_with(".part") || lower.ends_with(".tmp")
}

fn is_probably_video_file(path: &Path) -> bool {
    let Ok(bytes) = fs::read(path) else {
        return false;
    };
    if bytes.len() < 4 {
        return false;
    }
    let ext = path
        .extension()
        .and_then(|ext| ext.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase();

    match ext.as_str() {
        "mp4" | "m4v" | "mov" => bytes.len() >= 12 && &bytes[4..8] == b"ftyp",
        "webm" | "mkv" => bytes.starts_with(&[0x1a, 0x45, 0xdf, 0xa3]),
        "avi" => bytes.len() >= 12 && bytes.starts_with(b"RIFF") && &bytes[8..12] == b"AVI ",
        "m3u8" => bytes.starts_with(b"#EXTM3U"),
        "ts" => bytes[0] == 0x47,
        _ => true,
    }
}

fn read_image_dimensions(path: &Path) -> Option<(u32, u32)> {
    let bytes = fs::read(path).ok()?;
    if bytes.len() >= 24 && bytes.starts_with(b"\x89PNG\r\n\x1a\n") {
        let width = u32::from_be_bytes(bytes[16..20].try_into().ok()?);
        let height = u32::from_be_bytes(bytes[20..24].try_into().ok()?);
        return Some((width, height));
    }

    if bytes.len() < 4 || bytes[0] != 0xff || bytes[1] != 0xd8 {
        return None;
    }

    let mut index = 2usize;
    while index + 9 < bytes.len() {
        while index < bytes.len() && bytes[index] != 0xff {
            index += 1;
        }
        while index < bytes.len() && bytes[index] == 0xff {
            index += 1;
        }
        if index >= bytes.len() {
            break;
        }
        let marker = bytes[index];
        index += 1;
        if marker == 0xd9 || marker == 0xda {
            break;
        }
        if index + 2 > bytes.len() {
            break;
        }
        let length = u16::from_be_bytes([bytes[index], bytes[index + 1]]) as usize;
        if length < 2 || index + length > bytes.len() {
            break;
        }
        if matches!(
            marker,
            0xc0 | 0xc1
                | 0xc2
                | 0xc3
                | 0xc5
                | 0xc6
                | 0xc7
                | 0xc9
                | 0xca
                | 0xcb
                | 0xcd
                | 0xce
                | 0xcf
        ) && length >= 7
        {
            let height = u16::from_be_bytes([bytes[index + 3], bytes[index + 4]]) as u32;
            let width = u16::from_be_bytes([bytes[index + 5], bytes[index + 6]]) as u32;
            return Some((width, height));
        }
        index += length;
    }
    None
}

fn clear_folder(path: PathBuf) -> Result<(), String> {
    if !path.exists() {
        return Ok(());
    }
    for entry in fs::read_dir(path).map_err(|error| format!("failed to read folder: {error}"))? {
        let entry = entry.map_err(|error| format!("failed to read folder entry: {error}"))?;
        let metadata = entry
            .metadata()
            .map_err(|error| format!("failed to read folder metadata: {error}"))?;
        if metadata.is_file() {
            fs::remove_file(entry.path())
                .map_err(|error| format!("failed to delete media file: {error}"))?;
        }
    }
    Ok(())
}

fn resolve_adb(adb_path: Option<String>) -> Result<PathBuf, String> {
    if let Some(path) = adb_path.filter(|path| !path.trim().is_empty()) {
        let path = PathBuf::from(path);
        if path.exists() {
            return Ok(path);
        }
        return Err(format!("adb path does not exist: {}", path.display()));
    }
    find_mumu_adb()
}

fn ensure_proxy_target_is_valid(host: &str, port: u16) -> Result<(), String> {
    if matches!(host, "127.0.0.1" | "localhost" | "::1") {
        return Err("MuMu cannot use 127.0.0.1 as the host proxy address. Select the computer LAN IP instead.".to_string());
    }

    let mut addrs = (host, port)
        .to_socket_addrs()
        .map_err(|error| format!("invalid proxy address {host}:{port}: {error}"))?;
    let Some(addr) = addrs.next() else {
        return Err(format!("invalid proxy address {host}:{port}"));
    };

    TcpStream::connect_timeout(&addr, Duration::from_millis(1500)).map_err(|error| {
        format!(
            "proxy is not reachable at {host}:{port}. Start capture first or choose the correct listening port. {error}"
        )
    })?;
    Ok(())
}

fn find_mumu_adb() -> Result<PathBuf, String> {
    let mut candidates = Vec::new();
    if let Ok(path) = env::var("MUMU_ADB") {
        candidates.push(PathBuf::from(path));
    }

    let roots = mumu_roots();
    for root in &roots {
        #[cfg(target_os = "windows")]
        {
            candidates.push(
                root.join("nx_device")
                    .join("12.0")
                    .join("shell")
                    .join("adb.exe"),
            );
            candidates.push(root.join("nx_main").join("adb.exe"));
        }
        #[cfg(not(target_os = "windows"))]
        {
            candidates.push(root.join("Contents").join("MacOS").join("adb"));
            candidates.push(root.join("Contents").join("Resources").join("adb"));
            candidates.push(
                root.join("Contents")
                    .join("Resources")
                    .join("shell")
                    .join("adb"),
            );
            candidates.push(root.join("nx_main").join("adb"));
        }
    }
    for root in roots {
        collect_adb_candidates(&root, 0, 8, &mut candidates);
    }

    #[cfg(target_os = "windows")]
    if let Ok(output) = Command::new("where.exe").arg("adb").output() {
        if output.status.success() {
            let stdout = String::from_utf8_lossy(&output.stdout);
            candidates.extend(stdout.lines().map(|line| PathBuf::from(line.trim())));
        }
    }

    #[cfg(not(target_os = "windows"))]
    if let Ok(output) = Command::new("sh").args(["-c", "command -v adb"]).output() {
        if output.status.success() {
            let stdout = String::from_utf8_lossy(&output.stdout);
            candidates.extend(stdout.lines().map(|line| PathBuf::from(line.trim())));
        }
    }

    candidates
        .into_iter()
        .find(|path| path.exists())
        .ok_or_else(|| {
            "MuMu adb was not found. Set MUMU_ADB to the adb path if auto-detect cannot find it."
                .to_string()
        })
}

fn mumu_roots() -> Vec<PathBuf> {
    let mut roots = Vec::new();

    #[cfg(target_os = "windows")]
    {
        for path in [
            r"D:\Software\MuMuPlayer",
            r"D:\Program Files\MuMuPlayer",
            r"C:\Program Files\MuMuPlayer",
            r"C:\Program Files\MuMu Player",
            r"C:\Program Files (x86)\MuMuPlayer",
            r"C:\Program Files (x86)\MuMu Player",
            r"C:\Program Files\Netease\MuMuPlayer",
            r"C:\Program Files\Netease\MuMu Player",
            r"C:\Program Files (x86)\Netease\MuMuPlayer",
            r"C:\Program Files (x86)\Netease\MuMu Player",
            r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0",
            r"C:\Program Files (x86)\Netease\MuMuPlayerGlobal-12.0",
        ] {
            push_unique_path(&mut roots, PathBuf::from(path));
        }

        for var in [
            "ProgramFiles",
            "ProgramFiles(x86)",
            "ProgramW6432",
            "LOCALAPPDATA",
            "APPDATA",
            "ProgramData",
        ] {
            if let Ok(base) = env::var(var) {
                add_windows_mumu_root_variants(&mut roots, Path::new(&base));
                collect_windows_mumu_roots(Path::new(&base), &mut roots);
            }
        }

        for drive in ["C:\\", "D:\\", "E:\\"] {
            let base = Path::new(drive);
            add_windows_mumu_root_variants(&mut roots, base);
            collect_windows_mumu_roots(base, &mut roots);
        }
    }

    #[cfg(target_os = "macos")]
    {
        roots.extend([
            PathBuf::from("/Applications/MuMuPlayer.app"),
            PathBuf::from("/Applications/MuMu Player.app"),
            PathBuf::from("/Applications/Netease/MuMuPlayer.app"),
            PathBuf::from("/Applications/Netease/MuMu Player.app"),
        ]);

        if let Ok(home) = env::var("HOME") {
            roots.push(
                PathBuf::from(&home)
                    .join("Applications")
                    .join("MuMuPlayer.app"),
            );
            roots.push(
                PathBuf::from(home)
                    .join("Applications")
                    .join("MuMu Player.app"),
            );
        }
        collect_mumu_app_roots(Path::new("/Applications"), &mut roots);
        if let Ok(home) = env::var("HOME") {
            collect_mumu_app_roots(&PathBuf::from(home).join("Applications"), &mut roots);
        }
    }
    roots
}

fn push_unique_path(paths: &mut Vec<PathBuf>, path: PathBuf) {
    if !paths.iter().any(|item| item == &path) {
        paths.push(path);
    }
}

#[cfg(target_os = "windows")]
fn add_windows_mumu_root_variants(roots: &mut Vec<PathBuf>, base: &Path) {
    for relative in [
        "MuMuPlayer",
        "MuMu Player",
        "Netease/MuMuPlayer",
        "Netease/MuMu Player",
        "Netease/MuMuPlayerGlobal-12.0",
        "Netease/MuMu Player 12",
        "Nemu",
        "NemuPlayer",
    ] {
        push_unique_path(roots, base.join(relative));
    }
}

#[cfg(target_os = "windows")]
fn collect_windows_mumu_roots(folder: &Path, roots: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(folder) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        let lower = name.to_ascii_lowercase();
        if path.is_dir()
            && (lower.contains("mumu") || lower.contains("netease") || lower.contains("nemu"))
        {
            push_unique_path(roots, path.clone());
            let Ok(children) = fs::read_dir(&path) else {
                continue;
            };
            for child in children.flatten() {
                let child_path = child.path();
                let Some(child_name) = child_path.file_name().and_then(|name| name.to_str()) else {
                    continue;
                };
                let child_lower = child_name.to_ascii_lowercase();
                if child_path.is_dir()
                    && (child_lower.contains("mumu")
                        || child_lower.contains("netease")
                        || child_lower.contains("nemu")
                        || child_lower.starts_with("nx_"))
                {
                    push_unique_path(roots, child_path);
                }
            }
        }
    }
}

#[cfg(target_os = "macos")]
fn collect_mumu_app_roots(folder: &Path, roots: &mut Vec<PathBuf>) {
    let Ok(entries) = fs::read_dir(folder) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
            continue;
        };
        if path.is_dir()
            && name.to_ascii_lowercase().contains("mumu")
            && name.to_ascii_lowercase().ends_with(".app")
        {
            roots.push(path);
        }
    }
}

fn collect_adb_candidates(
    root: &Path,
    depth: usize,
    max_depth: usize,
    candidates: &mut Vec<PathBuf>,
) {
    if depth > max_depth || !root.exists() {
        return;
    }
    let Ok(entries) = fs::read_dir(root) else {
        return;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_file()
            && path
                .file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| {
                    name.eq_ignore_ascii_case("adb.exe") || name.eq_ignore_ascii_case("adb")
                })
        {
            candidates.push(path);
        } else if path.is_dir() {
            collect_adb_candidates(&path, depth + 1, max_depth, candidates);
        }
    }
}

fn mumu_adb_ports() -> Vec<u16> {
    vec![7555, 5555, 16384, 16416]
}

fn connect_mumu_device(adb: &Path) -> Result<String, String> {
    if let Some(device) = adb_devices(adb)?
        .into_iter()
        .find(|device| device.starts_with("127.0.0.1:"))
    {
        return Ok(device);
    }

    let mut connect_output = Vec::new();
    for port in mumu_adb_ports() {
        let target = format!("127.0.0.1:{port}");
        if let Ok(output) = run_adb(adb, &["connect", &target]) {
            connect_output.push(output);
        }
        if let Some(device) = adb_devices(adb)?
            .into_iter()
            .find(|device| device == &target)
        {
            return Ok(device);
        }
    }

    Err(format!(
        "no MuMu adb device connected. Tried ports {:?}. Output: {}",
        mumu_adb_ports(),
        connect_output.join("\n")
    ))
}

fn adb_devices(adb: &Path) -> Result<Vec<String>, String> {
    let output = run_adb(adb, &["devices"])?;
    Ok(output
        .lines()
        .filter_map(|line| {
            let mut parts = line.split_whitespace();
            let device = parts.next()?;
            let state = parts.next()?;
            if state == "device" {
                Some(device.to_string())
            } else {
                None
            }
        })
        .collect())
}

fn run_adb(adb: &Path, args: &[&str]) -> Result<String, String> {
    let output = Command::new(adb)
        .args(args)
        .output()
        .map_err(|error| format!("failed to run adb: {error}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    if output.status.success() {
        Ok(format!("{stdout}{stderr}"))
    } else {
        Err(format!("adb failed: {stdout}{stderr}"))
    }
}

fn normalize_easytool_base_url(base_url: &str) -> Result<String, String> {
    let value = base_url.trim().trim_end_matches('/');
    if value.is_empty() {
        return Err("EasyTool API address is empty".to_string());
    }
    if !(value.starts_with("http://") || value.starts_with("https://")) {
        return Err("EasyTool API address must start with http:// or https://".to_string());
    }
    Ok(value.to_string())
}

fn file_part(path: &str) -> Result<Part, String> {
    let path_buf = PathBuf::from(path);
    let bytes = fs::read(&path_buf)
        .map_err(|error| format!("failed to read upload file {}: {error}", path_buf.display()))?;
    let filename = path_buf
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("media")
        .to_string();
    let mime = mime_from_path(&path_buf);
    Part::bytes(bytes)
        .file_name(filename)
        .mime_str(mime)
        .map_err(|error| format!("failed to prepare upload file: {error}"))
}

fn mime_from_path(path: &Path) -> &'static str {
    match path
        .extension()
        .and_then(|ext| ext.to_str())
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "jpg" | "jpeg" => "image/jpeg",
        "png" => "image/png",
        "webp" => "image/webp",
        "gif" => "image/gif",
        "bmp" => "image/bmp",
        "heic" => "image/heic",
        "heif" => "image/heif",
        "mp4" | "m4v" => "video/mp4",
        "mov" => "video/quicktime",
        "webm" => "video/webm",
        "avi" => "video/x-msvideo",
        "mkv" => "video/x-matroska",
        _ => "application/octet-stream",
    }
}

fn parse_easytool_response<T>(
    response: reqwest::blocking::Response,
    context: &str,
) -> Result<T, String>
where
    T: for<'de> Deserialize<'de>,
{
    let status = response.status();
    let text = response
        .text()
        .map_err(|error| format!("{context}: failed to read response: {error}"))?;
    let parsed: EasyToolApiResponse<T> = match serde_json::from_str(&text) {
        Ok(parsed) => parsed,
        Err(error) => {
            if let Ok(value) = serde_json::from_str::<serde_json::Value>(&text) {
                let server_status = value
                    .get("status")
                    .and_then(|status| status.as_i64())
                    .map(|status| status.to_string())
                    .unwrap_or_else(|| status.as_u16().to_string());
                let server_error = value
                    .get("error")
                    .and_then(|error| error.as_str())
                    .unwrap_or("unexpected response");
                let path = value
                    .get("path")
                    .and_then(|path| path.as_str())
                    .unwrap_or("");
                if server_status == "404" {
                    return Err(format!(
                        "{context}: EasyTool endpoint not found (HTTP 404). Restart EasyTool backend or check EasyTool address. Path: {path}"
                    ));
                }
                return Err(format!(
                    "{context}: EasyTool returned unexpected response (HTTP {server_status} {server_error}). {text}"
                ));
            }
            return Err(format!(
                "{context}: EasyTool returned non-JSON response (HTTP {status}): {error}. {text}"
            ));
        }
    };
    if !status.is_success() || parsed.code != 200 {
        return Err(format!(
            "{context}: {}",
            parsed
                .message
                .unwrap_or_else(|| format!("HTTP {status}, code {}", parsed.code))
        ));
    }
    parsed
        .data
        .ok_or_else(|| format!("{context}: EasyTool response has no data"))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(CaptureState::default())
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            get_capture_status,
            start_capture,
            stop_capture,
            get_local_ips,
            list_media,
            delete_file,
            read_media_data_url,
            clear_media,
            open_path,
            detect_mumu_adb,
            set_mumu_wifi_proxy,
            clear_mumu_wifi_proxy,
            easytool_login,
            easytool_upload_personal_media
        ])
        .run(tauri::generate_context!())
        .expect("error while running Dewu capture app");
}
