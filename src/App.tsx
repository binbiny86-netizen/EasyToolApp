import {
  Activity,
  Cable,
  Camera,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Copy,
  ExternalLink,
  FolderOpen,
  Image as ImageIcon,
  LogIn,
  Play,
  RefreshCw,
  Search,
  Settings,
  Square,
  Trash2,
  UploadCloud,
  Video,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { AdbInfo, api, CaptureConfig, CaptureLog, EasyToolSettings, MediaFile } from "./api";

type Tab = "capture" | "gallery" | "logs" | "settings";
type GalleryTab = "images" | "videos";
type AspectFilter = "all" | "landscape" | "portrait" | "square" | "1:1" | "3:4" | "4:3" | "9:16" | "16:9";

const pageSize = 50;
const settingsKey = "dewu-capture-settings";
const easyToolSettingsKey = "dewu-easytool-settings";

const defaultSettings: CaptureConfig = {
  port: 8080,
  outputRoot: ".",
  debugMode: true,
  jpegQuality: 95,
  hostKeywords: ["dewu", "poizon", "shihuo", "dewucdn", "dewuimg", "aliyuncs"],
  mitmdumpCommand: "mitmdump",
  adbPath: "",
};

const defaultEasyToolSettings: EasyToolSettings = {
  baseUrl: "http://10.110.134.81:8080",
  username: "",
  password: "",
  token: "",
  productId: "",
};

const setupGroups = [
  {
    platform: "Windows",
    cards: [
      {
        title: "1. 安装 Rust/Cargo",
        body: "Tauri 桌面窗口需要 Rust 工具链。安装后重新打开 PowerShell。",
        command: "winget install Rustlang.Rustup",
        check: "cargo --version",
      },
      {
        title: "2. 安装 C++ Build Tools",
        body: "Windows 打包和运行 Tauri 需要 MSVC。没有 winget 时可下载安装器后安装 VCTools。",
        command: "winget install Microsoft.VisualStudio.2022.BuildTools",
        check: "cl 或 link",
      },
      {
        title: "2b. 无 winget 备用命令",
        body: "适合精简系统。命令会下载微软官方安装器并安装 C++ Build Tools。",
        command:
          "iwr https://aka.ms/vs/17/release/vs_BuildTools.exe -OutFile $env:TEMP\\vs_BuildTools.exe; & $env:TEMP\\vs_BuildTools.exe --quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended",
        check: "VsDevCmd.bat 后 where link",
      },
      {
        title: "3. 安装 Python 采集依赖",
        body: "mitmproxy 负责代理抓包，Pillow 负责图片转换。",
        command: "py -m pip install mitmproxy Pillow pillow-heif",
        check: "py -m mitmproxy --version",
      },
      {
        title: "4. 启动桌面 App",
        body: "进入项目目录后启动 Tauri 开发模式。",
        command: "npm.cmd install && npm.cmd run tauri dev",
        check: "npm.cmd run build",
      },
    ],
  },
  {
    platform: "macOS",
    cards: [
      {
        title: "1. 安装 Xcode 工具",
        body: "Tauri 在 macOS 上需要系统编译工具。安装后重新打开终端。",
        command: "xcode-select --install",
        check: "xcode-select -p",
      },
      {
        title: "2. 安装 Node 和 Rust",
        body: "建议用 Homebrew 安装 Node，再用 rustup 安装 Cargo。",
        command: "brew install node && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh",
        check: "node -v && cargo --version",
      },
      {
        title: "3. 安装 Python 采集依赖",
        body: "Apple Silicon 默认常用 Homebrew 路径，App 也会自动查找这些路径。",
        command: "python3 -m pip install mitmproxy Pillow pillow-heif",
        check: "python3 -m mitmproxy --version",
      },
      {
        title: "4. 指定 MuMu ADB",
        body: "如果自动检测不到 MuMu 自带 adb，就把 MUMU_ADB 指到实际 adb 路径。",
        command: "export MUMU_ADB=/path/to/adb",
        check: "adb devices 或 echo $MUMU_ADB",
      },
      {
        title: "5. 启动桌面 App",
        body: "进入项目目录后启动 Tauri 开发模式，端口和 Windows 一样可在设置里改。",
        command: "npm install && npm run tauri dev",
        check: "npm run build",
      },
    ],
  },
];

function loadSettings(): CaptureConfig {
  const raw = localStorage.getItem(settingsKey);
  if (!raw) return defaultSettings;
  try {
    const settings = { ...defaultSettings, ...JSON.parse(raw) };
    if (settings.mitmdumpCommand === "py -m mitmproxy.tools.main mitmdump") {
      settings.mitmdumpCommand = defaultSettings.mitmdumpCommand;
    }
    return settings;
  } catch {
    return defaultSettings;
  }
}

function saveSettings(settings: CaptureConfig) {
  localStorage.setItem(settingsKey, JSON.stringify(settings));
}

function loadEasyToolSettings(): EasyToolSettings {
  const raw = localStorage.getItem(easyToolSettingsKey);
  if (!raw) return defaultEasyToolSettings;
  try {
    return { ...defaultEasyToolSettings, ...JSON.parse(raw), password: "" };
  } catch {
    return defaultEasyToolSettings;
  }
}

function saveEasyToolSettings(settings: EasyToolSettings) {
  const { password: _password, ...stored } = settings;
  localStorage.setItem(easyToolSettingsKey, JSON.stringify(stored));
}

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>("capture");
  const [galleryTab, setGalleryTab] = useState<GalleryTab>("images");
  const [settings, setSettings] = useState<CaptureConfig>(() => loadSettings());
  const [easyToolSettings, setEasyToolSettings] = useState<EasyToolSettings>(() => loadEasyToolSettings());
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [easyToolBusy, setEasyToolBusy] = useState(false);
  const [localIps, setLocalIps] = useState<string[]>(["127.0.0.1"]);
  const [selectedIp, setSelectedIp] = useState("127.0.0.1");
  const [images, setImages] = useState<MediaFile[]>([]);
  const [videos, setVideos] = useState<MediaFile[]>([]);
  const [logs, setLogs] = useState<CaptureLog[]>([]);
  const [notice, setNotice] = useState("");
  const [adbInfo, setAdbInfo] = useState<AdbInfo | null>(null);
  const [adbBusy, setAdbBusy] = useState(false);
  const [galleryPage, setGalleryPage] = useState(1);
  const [previewIndex, setPreviewIndex] = useState<number | null>(null);
  const [aspectFilter, setAspectFilter] = useState<AspectFilter>("all");
  const [easyToolImagePaths, setEasyToolImagePaths] = useState<string[]>([]);
  const [easyToolVideoPath, setEasyToolVideoPath] = useState("");

  const proxyAddress = `${selectedIp}:${settings.port}`;
  const activeFiles = galleryTab === "images" ? filterImagesByAspect(images, aspectFilter) : videos;
  const pageCount = Math.max(1, Math.ceil(activeFiles.length / pageSize));
  const safePage = Math.min(galleryPage, pageCount);
  const pageStart = (safePage - 1) * pageSize;
  const pagedFiles = activeFiles.slice(pageStart, pageStart + pageSize);
  const previewFile = previewIndex === null ? null : activeFiles[previewIndex] ?? null;

  useEffect(() => {
    saveSettings(settings);
  }, [settings]);

  useEffect(() => {
    saveEasyToolSettings(easyToolSettings);
  }, [easyToolSettings]);

  useEffect(() => {
    setGalleryPage(1);
    setPreviewIndex(null);
  }, [galleryTab, aspectFilter]);

  useEffect(() => {
    setGalleryPage((current) => Math.min(current, pageCount));
    if (previewIndex !== null && previewIndex >= activeFiles.length) {
      setPreviewIndex(activeFiles.length ? activeFiles.length - 1 : null);
    }
  }, [activeFiles.length, pageCount, previewIndex]);

  useEffect(() => {
    const imagePathSet = new Set(images.map((file) => file.path));
    setEasyToolImagePaths((current) => current.filter((path) => imagePathSet.has(path)));
    if (easyToolVideoPath && !videos.some((file) => file.path === easyToolVideoPath)) {
      setEasyToolVideoPath("");
    }
  }, [easyToolVideoPath, images, videos]);

  useEffect(() => {
    let unlisten: (() => void) | undefined;
    api.getCaptureStatus().then((status) => setRunning(status.running)).catch(showError);
    api
      .getLocalIps()
      .then((ips) => {
        setLocalIps(ips);
        setSelectedIp(ips[0] ?? "127.0.0.1");
      })
      .catch(showError);
    refreshMedia();
    const timer = window.setInterval(refreshMedia, 2500);
    api.onCaptureLog((log) => {
      setLogs((current) => [...current.slice(-299), log]);
    }).then((cleanup) => {
      unlisten = cleanup;
    });
    return () => {
      window.clearInterval(timer);
      unlisten?.();
    };
  }, []);

  const counters = useMemo(
    () => [
      { label: "图片", value: images.length, icon: ImageIcon },
      { label: "视频", value: videos.length, icon: Video },
      { label: "端口", value: settings.port, icon: Activity },
    ],
    [images.length, settings.port, videos.length],
  );

  function showError(error: unknown) {
    setNotice(error instanceof Error ? error.message : String(error));
  }

  async function refreshMedia() {
    try {
      const media = await api.listMedia(settings.outputRoot);
      setImages(media.images);
      setVideos(media.videos);
    } catch (error) {
      showError(error);
    }
  }

  async function startCapture() {
    setBusy(true);
    setNotice("");
    try {
      const status = await api.startCapture(settings);
      setRunning(status.running);
      setLogs((current) => [
        ...current,
        { stream: "app", line: `capture started on ${proxyAddress}` },
      ]);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  }

  async function stopCapture() {
    setBusy(true);
    try {
      const status = await api.stopCapture();
      setRunning(status.running);
      setLogs((current) => [...current, { stream: "app", line: "capture stopped" }]);
    } catch (error) {
      showError(error);
    } finally {
      setBusy(false);
    }
  }

  async function copyProxyAddress() {
    await navigator.clipboard.writeText(proxyAddress);
    setNotice(`已复制代理地址 ${proxyAddress}`);
  }


  async function detectMumuAdb() {
    setAdbBusy(true);
    setNotice("");
    try {
      const info = await api.detectMumuAdb(settings.adbPath);
      const adbPath = settings.adbPath?.trim() || info.adbPath || "";
      setAdbInfo({ ...info, adbPath: adbPath || undefined });
      if (info.adbPath && info.adbPath !== settings.adbPath) {
        const nextSettings = { ...settings, adbPath: info.adbPath };
        setSettings(nextSettings);
        saveSettings(nextSettings);
      }
      setNotice(adbPath ? `已找到 MuMu ADB：${adbPath}` : "没有找到 MuMu ADB，请在下方填写 adb.exe 完整路径。");
    } catch (error) {
      showError(error);
    } finally {
      setAdbBusy(false);
    }
  }

  async function setMumuProxy() {
    setAdbBusy(true);
    setNotice("");
    try {
      const adbPath = settings.adbPath?.trim() || adbInfo?.adbPath;
      const result = await api.setMumuWifiProxy(selectedIp, settings.port, adbPath);
      setAdbInfo((current) => ({
        adbPath: result.adbPath,
        devices: [result.device],
        candidatePorts: current?.candidatePorts ?? [],
      }));
      const nextSettings = { ...settings, adbPath: result.adbPath };
      setSettings(nextSettings);
      saveSettings(nextSettings);
      setLogs((current) => [
        ...current,
        { stream: "adb", line: `MuMu proxy set to ${result.proxy} on ${result.device}` },
      ]);
      setNotice(`已通过 ADB 设置 MuMu 代理：${result.proxy}`);
    } catch (error) {
      showError(error);
    } finally {
      setAdbBusy(false);
    }
  }

  async function clearMumuProxy() {
    setAdbBusy(true);
    setNotice("");
    try {
      const result = await api.clearMumuWifiProxy(settings.adbPath?.trim() || adbInfo?.adbPath);
      setLogs((current) => [...current, { stream: "adb", line: `MuMu proxy cleared on ${result.device}` }]);
      setNotice("已清除 MuMu Wi-Fi 代理。");
    } catch (error) {
      showError(error);
    } finally {
      setAdbBusy(false);
    }
  }

  async function loginEasyTool() {
    setEasyToolBusy(true);
    setNotice("");
    try {
      const result = await api.easyToolLogin(
        easyToolSettings.baseUrl,
        easyToolSettings.username,
        easyToolSettings.password,
      );
      setEasyToolSettings((current) => ({
        ...current,
        token: result.token,
        username: result.username || current.username,
        password: "",
      }));
      setNotice(`EasyTool 已登录：${result.displayName || result.username || easyToolSettings.username}`);
    } catch (error) {
      showError(error);
    } finally {
      setEasyToolBusy(false);
    }
  }

  function toggleEasyToolImage(path: string) {
    setEasyToolImagePaths((current) =>
      current.includes(path)
        ? current.filter((item) => item !== path)
        : [...current, path],
    );
  }

  async function uploadEasyToolMedia() {
    const productId = Number(easyToolSettings.productId);
    if (!Number.isFinite(productId) || productId <= 0) {
      setNotice("请填写 EasyTool 个人商品 ID。");
      return;
    }
    if (!easyToolImagePaths.length && !easyToolVideoPath) {
      setNotice("请选择要上传到 EasyTool 的图片或视频。");
      return;
    }

    setEasyToolBusy(true);
    setNotice("");
    try {
      const result = await api.uploadEasyToolPersonalMedia(
        easyToolSettings.baseUrl,
        easyToolSettings.token,
        Math.round(productId),
        easyToolImagePaths,
        easyToolVideoPath || undefined,
      );
      setNotice(
        `EasyTool 已更新个人商品 ${result.productId}：AI参考图 +${result.addedImageCount ?? 0}${
          result.videoUpdated ? "，产品视频已覆盖" : ""
        }`,
      );
      setEasyToolImagePaths([]);
      setEasyToolVideoPath("");
    } catch (error) {
      showError(error);
    } finally {
      setEasyToolBusy(false);
    }
  }

  async function deleteMedia(file: MediaFile) {
    if (!window.confirm(`删除 ${file.name}？`)) return;
    await api.deleteFile(file.path);
    setPreviewIndex(null);
    await refreshMedia();
  }

  async function clearCurrentMedia() {
    const kind = galleryTab === "images" ? "image" : "video";
    if (!window.confirm(`清空当前${galleryTab === "images" ? "图片" : "视频"}列表？`)) return;
    await api.clearMedia(settings.outputRoot, kind);
    setPreviewIndex(null);
    await refreshMedia();
  }

  async function clearAllMedia() {
    if (!window.confirm("删除全部图片和视频？")) return;
    await api.clearMedia(settings.outputRoot, "all");
    setPreviewIndex(null);
    await refreshMedia();
  }

  function showPreviousPreview() {
    setPreviewIndex((current) => {
      if (current === null || activeFiles.length === 0) return current;
      return current <= 0 ? activeFiles.length - 1 : current - 1;
    });
  }

  function showNextPreview() {
    setPreviewIndex((current) => {
      if (current === null || activeFiles.length === 0) return current;
      return current >= activeFiles.length - 1 ? 0 : current + 1;
    });
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <Camera size={22} />
          </div>
          <div>
            <strong>得物采集</strong>
            <span>MuMu 控制台</span>
          </div>
        </div>

        <nav>
          <NavButton icon={Activity} label="采集" active={activeTab === "capture"} onClick={() => setActiveTab("capture")} />
          <NavButton icon={ImageIcon} label="素材" active={activeTab === "gallery"} onClick={() => setActiveTab("gallery")} />
          <NavButton icon={ExternalLink} label="日志" active={activeTab === "logs"} onClick={() => setActiveTab("logs")} />
          <NavButton icon={Settings} label="设置" active={activeTab === "settings"} onClick={() => setActiveTab("settings")} />
        </nav>

        <div className={`status ${running ? "running" : ""}`}>
          <span />
          {running ? "采集中" : "已停止"}
        </div>
      </aside>

      <main className="content">
        {notice && (
          <div className="notice">
            <CheckCircle2 size={18} />
            <span>{notice}</span>
            <button onClick={() => setNotice("")}>关闭</button>
          </div>
        )}

        {activeTab === "capture" && (
          <section className="screen">
            <div className="screen-header">
              <div>
                <p className="eyebrow">Capture</p>
                <h1>MuMu 代理采集</h1>
              </div>
              <div className="actions">
                <button className="secondary" onClick={refreshMedia}>
                  <RefreshCw size={18} />
                  刷新
                </button>
                {running ? (
                  <button className="danger" disabled={busy} onClick={stopCapture}>
                    <Square size={18} />
                    停止
                  </button>
                ) : (
                  <button className="primary" disabled={busy} onClick={startCapture}>
                    <Play size={18} />
                    启动
                  </button>
                )}
              </div>
            </div>

            <div className="metric-grid">
              {counters.map((item) => (
                <div className="metric" key={item.label}>
                  <item.icon size={20} />
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                </div>
              ))}
            </div>

            <div className="work-area">
              <section className="panel setup-panel">
                <div className="panel-title">
                  <h2>代理地址</h2>
                  <button className="icon-button" title="复制代理地址" onClick={copyProxyAddress}>
                    <Copy size={18} />
                  </button>
                </div>
                <div className="proxy-address">{proxyAddress}</div>
                <label className="field">
                  <span>本机 IP</span>
                  <select value={selectedIp} onChange={(event) => setSelectedIp(event.target.value)}>
                    {localIps.map((ip) => (
                      <option key={ip} value={ip}>
                        {ip}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>监听端口</span>
                  <input
                    disabled={running}
                    type="number"
                    min={1}
                    max={65535}
                    value={settings.port}
                    onChange={(event) => setSettings({ ...settings, port: clampPort(Number(event.target.value)) })}
                  />
                </label>
                {running && <p className="hint">采集中不能修改端口，请先停止后再调整。</p>}
                <div className="adb-box">
                  <div>
                    <strong>MuMu ADB 代理</strong>
                    <span>{settings.adbPath || adbInfo?.adbPath ? `ADB：${settings.adbPath || adbInfo?.adbPath}` : "自动查找 MuMu 自带 ADB"}</span>
                    {adbInfo?.devices.length ? <span>设备：{adbInfo.devices.join(", ")}</span> : null}
                  </div>
                  <label className="field">
                    <span>ADB 路径</span>
                    <input
                      placeholder="例如 D:\\Software\\MuMuPlayer\\nx_device\\12.0\\shell\\adb.exe"
                      value={settings.adbPath || ""}
                      onChange={(event) => {
                        const nextSettings = { ...settings, adbPath: event.target.value };
                        setSettings(nextSettings);
                        saveSettings(nextSettings);
                      }}
                    />
                  </label>
                  <div className="adb-actions">
                    <button className="secondary" disabled={adbBusy} onClick={detectMumuAdb}>
                      <Search size={17} />
                      检测
                    </button>
                    <button className="primary" disabled={adbBusy || !running} onClick={setMumuProxy}>
                      <Cable size={17} />
                      设置代理
                    </button>
                    <button className="secondary" disabled={adbBusy} onClick={clearMumuProxy}>
                      <Square size={17} />
                      清除
                    </button>
                  </div>
                  {!running ? <p className="hint">请先启动采集，再把 MuMu 代理指向当前端口。</p> : null}
                </div>
                <ol className="steps">
                  <li>点击“设置代理”可通过 MuMu ADB 自动写入 Wi-Fi 代理。</li>
                  <li>代理值使用上面的 IP 和监听端口：{proxyAddress}。</li>
                  <li>在 MuMu 浏览器访问 http://mitm.it 安装并信任证书。</li>
                  <li>打开得物 App，正常浏览商品。</li>
                </ol>
              </section>

              <section className="panel recent-panel">
                <div className="panel-title">
                  <h2>最近事件</h2>
                  <span>{logs.length} 条</span>
                </div>
                <LogList logs={logs.slice(-8).reverse()} compact />
              </section>
            </div>

            <section className="panel environment-panel">
              <div className="panel-title">
                <div>
                  <h2>新电脑环境安装流程</h2>
                  <p>换电脑运行时，先按顺序准备这些依赖，再回到这里启动采集。</p>
                </div>
              </div>
              <div className="install-grid">
                {setupGroups.map((group) => (
                  <div className="install-group" key={group.platform}>
                    <h3>{group.platform}</h3>
                    <div className="install-group-grid">
                      {group.cards.map((card) => (
                        <article className="install-card" key={`${group.platform}-${card.title}`}>
                          <h4>{card.title}</h4>
                          <p>{card.body}</p>
                          <div className="command-row">
                            <code>{card.command}</code>
                            <button className="icon-button" title="复制安装命令" onClick={() => navigator.clipboard.writeText(card.command)}>
                              <Copy size={17} />
                            </button>
                          </div>
                          <span>验证：{card.check}</span>
                        </article>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </section>
        )}

        {activeTab === "gallery" && (
          <section className="screen">
            <div className="screen-header">
              <div>
                <p className="eyebrow">Library</p>
                <h1>采集素材</h1>
              </div>
              <div className="actions">
                <button className="secondary" onClick={() => api.openPath(settings.outputRoot)}>
                  <FolderOpen size={18} />
                  打开目录
                </button>
                <button className="danger ghost" onClick={clearCurrentMedia}>
                  <Trash2 size={18} />
                  清空当前
                </button>
                <button className="danger" onClick={clearAllMedia}>
                  <Trash2 size={18} />
                  全部删除
                </button>
              </div>
            </div>

            <div className="segmented">
              <button className={galleryTab === "images" ? "active" : ""} onClick={() => setGalleryTab("images")}>
                <ImageIcon size={18} />
                图片 {images.length}
              </button>
              <button className={galleryTab === "videos" ? "active" : ""} onClick={() => setGalleryTab("videos")}>
                <Video size={18} />
                视频 {videos.length}
              </button>
            </div>

            {galleryTab === "images" && (
              <div className="filter-bar">
                <label className="field compact-field">
                  <span>图片比例</span>
                  <select value={aspectFilter} onChange={(event) => setAspectFilter(event.target.value as AspectFilter)}>
                    <option value="all">全部比例</option>
                    <option value="landscape">横图</option>
                    <option value="portrait">竖图</option>
                    <option value="square">方图</option>
                    <option value="1:1">1:1</option>
                    <option value="3:4">3:4</option>
                    <option value="4:3">4:3</option>
                    <option value="9:16">9:16</option>
                    <option value="16:9">16:9</option>
                  </select>
                </label>
                <span>当前筛选 {activeFiles.length} 张</span>
              </div>
            )}

            <section className="panel easytool-gallery-panel">
              <div className="easytool-bar">
                <div className="easytool-main">
                  <strong>EasyTool 个人商品</strong>
                  <span>AI参考图 {easyToolImagePaths.length} 张 · 产品视频 {easyToolVideoPath ? "已选" : "未选"}</span>
                </div>
                <label className="field easytool-product-field">
                  <span>个人商品 ID</span>
                  <input
                    value={easyToolSettings.productId}
                    onChange={(event) => setEasyToolSettings({ ...easyToolSettings, productId: event.target.value.replace(/[^\d]/g, "") })}
                    placeholder="例如 123"
                  />
                </label>
                <button className="secondary easytool-login-button" disabled={easyToolBusy} onClick={loginEasyTool}>
                  <LogIn size={17} />
                  登录
                </button>
                <button className="primary" disabled={easyToolBusy} onClick={uploadEasyToolMedia}>
                  <UploadCloud size={18} />
                  上传
                </button>
                {easyToolImagePaths.length > 0 || easyToolVideoPath ? (
                  <button
                    className="secondary compact-action"
                    onClick={() => {
                      setEasyToolImagePaths([]);
                      setEasyToolVideoPath("");
                    }}
                  >
                    清空选择
                  </button>
                ) : null}
              </div>
              <details className="easytool-connection">
                <summary>连接设置</summary>
                <div className="easytool-settings-grid">
                  <label className="field">
                    <span>EasyTool 地址</span>
                    <input
                      value={easyToolSettings.baseUrl}
                      onChange={(event) => setEasyToolSettings({ ...easyToolSettings, baseUrl: event.target.value })}
                      placeholder="http://10.110.134.81:8080"
                    />
                  </label>
                  <label className="field">
                    <span>用户名</span>
                    <input
                      value={easyToolSettings.username}
                      onChange={(event) => setEasyToolSettings({ ...easyToolSettings, username: event.target.value })}
                    />
                  </label>
                  <label className="field">
                    <span>密码</span>
                    <input
                      type="password"
                      value={easyToolSettings.password}
                      onChange={(event) => setEasyToolSettings({ ...easyToolSettings, password: event.target.value })}
                    />
                  </label>
                  <label className="field easytool-token-field">
                    <span>Token</span>
                    <input
                      value={easyToolSettings.token}
                      onChange={(event) => setEasyToolSettings({ ...easyToolSettings, token: event.target.value })}
                      placeholder="登录后自动填入"
                    />
                  </label>
                </div>
              </details>
            </section>

            {activeFiles.length > 0 && (
              <div className="pagination-bar">
                <span>
                  第 {safePage} / {pageCount} 页，每页 {pageSize} 个，共 {activeFiles.length} 个
                </span>
                <div className="pagination-actions">
                  <button className="secondary" disabled={safePage <= 1} onClick={() => setGalleryPage((page) => Math.max(1, page - 1))}>
                    <ChevronLeft size={17} />
                    上一页
                  </button>
                  <button className="secondary" disabled={safePage >= pageCount} onClick={() => setGalleryPage((page) => Math.min(pageCount, page + 1))}>
                    下一页
                    <ChevronRight size={17} />
                  </button>
                </div>
              </div>
            )}

            <div className="media-grid">
              {pagedFiles.map((file, index) => (
                <MediaCard
                  file={file}
                  key={file.path}
                  onDelete={() => deleteMedia(file)}
                  onOpen={() => api.openPath(file.path)}
                  onPreview={() => setPreviewIndex(pageStart + index)}
                  onSelect={() =>
                    file.kind === "image"
                      ? toggleEasyToolImage(file.path)
                      : setEasyToolVideoPath(file.path)
                  }
                  selected={file.kind === "image" ? easyToolImagePaths.includes(file.path) : easyToolVideoPath === file.path}
                  selectLabel={file.kind === "image" ? "AI参考图" : "产品视频"}
                />
              ))}
              {activeFiles.length === 0 && (
                <div className="empty-state">
                  <ImageIcon size={34} />
                  <p>还没有采集到素材</p>
                  <span>启动采集后，浏览得物商品，这里会自动刷新。</span>
                </div>
              )}
            </div>
          </section>
        )}

        {activeTab === "logs" && (
          <section className="screen">
            <div className="screen-header">
              <div>
                <p className="eyebrow">Logs</p>
                <h1>运行日志</h1>
              </div>
              <button className="secondary" onClick={() => setLogs([])}>
                <Trash2 size={18} />
                清空日志
              </button>
            </div>
            <div className="log-panel">
              <LogList logs={logs.slice().reverse()} />
            </div>
          </section>
        )}

        {activeTab === "settings" && (
          <section className="screen">
            <div className="screen-header">
              <div>
                <p className="eyebrow">Settings</p>
                <h1>采集设置</h1>
              </div>
            </div>

            <div className="settings-grid">
              <label className="field">
                <span>代理端口</span>
                <input
                  type="number"
                  min={1}
                  max={65535}
                  value={settings.port}
                  onChange={(event) => setSettings({ ...settings, port: clampPort(Number(event.target.value)) })}
                />
              </label>
              <label className="field">
                <span>输出目录</span>
                <input value={settings.outputRoot} onChange={(event) => setSettings({ ...settings, outputRoot: event.target.value })} />
              </label>
              <label className="field">
                <span>mitmdump 命令</span>
                <input value={settings.mitmdumpCommand} onChange={(event) => setSettings({ ...settings, mitmdumpCommand: event.target.value })} />
              </label>
              <label className="field">
                <span>JPEG 质量</span>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={settings.jpegQuality}
                  onChange={(event) => setSettings({ ...settings, jpegQuality: Number(event.target.value) })}
                />
              </label>
              <label className="field wide">
                <span>域名关键词</span>
                <input
                  value={settings.hostKeywords.join(",")}
                  onChange={(event) =>
                    setSettings({
                      ...settings,
                      hostKeywords: event.target.value
                        .split(",")
                        .map((item) => item.trim())
                        .filter(Boolean),
                    })
                  }
                />
              </label>
              <label className="toggle wide">
                <input type="checkbox" checked={settings.debugMode} onChange={(event) => setSettings({ ...settings, debugMode: event.target.checked })} />
                <span>写入调试请求日志</span>
              </label>
            </div>
          </section>
        )}
      </main>

      {previewFile && previewIndex !== null && (
        <PreviewModal
          file={previewFile}
          index={previewIndex}
          total={activeFiles.length}
          onClose={() => setPreviewIndex(null)}
          onDelete={() => deleteMedia(previewFile)}
          onNext={showNextPreview}
          onOpen={() => api.openPath(previewFile.path)}
          onPrevious={showPreviousPreview}
        />
      )}
    </div>
  );
}

function NavButton({
  icon: Icon,
  label,
  active,
  onClick,
}: {
  icon: typeof Activity;
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button className={active ? "active" : ""} onClick={onClick}>
      <Icon size={19} />
      <span>{label}</span>
    </button>
  );
}

function MediaCard({
  file,
  onDelete,
  onOpen,
  onPreview,
  onSelect,
  selected = false,
  selectLabel,
}: {
  file: MediaFile;
  onDelete: () => void;
  onOpen: () => void;
  onPreview: () => void;
  onSelect?: () => void;
  selected?: boolean;
  selectLabel?: string;
}) {
  const isImage = file.kind === "image";
  const [src] = useMediaDataUrl(isImage ? file.path : "");
  const videoSrc = isImage ? "" : api.mediaFileSrc(file.path);
  const [videoThumbReady, setVideoThumbReady] = useState(false);
  const selectTitle = selected
    ? isImage
      ? `取消选择${selectLabel || "素材"}`
      : `已选为${selectLabel || "素材"}`
    : `选择${selectLabel || "素材"}`;

  return (
    <article className={selected ? "media-card selected" : "media-card"}>
      <button className="media-preview" onClick={onPreview} title="预览">
        {isImage && src ? (
          <img src={src} alt={file.name} />
        ) : videoSrc ? (
          <>
            <video
              className={videoThumbReady ? "media-video-thumb" : "media-video-thumb loading"}
              src={videoSrc}
              muted
              preload="metadata"
              playsInline
              onLoadedData={() => setVideoThumbReady(true)}
              onError={() => setVideoThumbReady(false)}
            />
            <span className="media-play-badge">
              <Play size={20} />
            </span>
          </>
        ) : (
          <Video size={42} />
        )}
        {selected && <span className="media-selected-badge">已选</span>}
      </button>
      <div className="media-meta">
        <strong title={file.name}>{file.name}</strong>
        <span>{[formatBytes(file.bytes), formatDimensions(file), formatTime(file.modifiedMs)].filter(Boolean).join(" | ")}</span>
      </div>
      <div className="media-actions">
        {onSelect && (
          <button className={selected ? "icon-button selected-icon" : "icon-button"} title={selectTitle} onClick={onSelect}>
            <CheckCircle2 size={17} />
          </button>
        )}
        <button className="icon-button" title="预览" onClick={onPreview}>
          <Search size={17} />
        </button>
        <button className="icon-button" title="打开文件" onClick={onOpen}>
          <ExternalLink size={17} />
        </button>
        <button className="icon-button danger-icon" title="删除文件" onClick={onDelete}>
          <Trash2 size={17} />
        </button>
      </div>
    </article>
  );
}

function PreviewModal({
  file,
  index,
  total,
  onClose,
  onDelete,
  onNext,
  onOpen,
  onPrevious,
}: {
  file: MediaFile;
  index: number;
  total: number;
  onClose: () => void;
  onDelete: () => void;
  onNext: () => void;
  onOpen: () => void;
  onPrevious: () => void;
}) {
  const isImage = file.kind === "image";
  const [src] = useMediaDataUrl(file.path);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft") onPrevious();
      if (event.key === "ArrowRight") onNext();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, onNext, onPrevious]);

  return (
    <div className="preview-modal" role="dialog" aria-modal="true">
      <div className="preview-toolbar">
        <div>
          <strong>{file.name}</strong>
          <span>{index + 1} / {total} {isImage ? "张" : "个"} {formatBytes(file.bytes)}</span>
        </div>
        <div className="preview-actions">
          <button className="icon-button" title="打开文件" onClick={onOpen}>
            <ExternalLink size={18} />
          </button>
          <button className="icon-button danger-icon" title="删除文件" onClick={onDelete}>
            <Trash2 size={18} />
          </button>
          <button className="icon-button" title="关闭" onClick={onClose}>
            <X size={19} />
          </button>
        </div>
      </div>

      <button className="preview-nav left" title="上一张" onClick={onPrevious}>
        <ChevronLeft size={32} />
      </button>
      <div className="preview-stage">
        {!src ? (
          <div className="preview-loading">加载中</div>
        ) : isImage ? (
          <img src={src} alt={file.name} />
        ) : (
          <video key={file.path} src={src} controls autoPlay playsInline preload="auto" />
        )}
      </div>
      <button className="preview-nav right" title="下一张" onClick={onNext}>
        <ChevronRight size={32} />
      </button>
    </div>
  );
}

function useMediaDataUrl(path: string) {
  const [src, setSrc] = useState("");

  useEffect(() => {
    let cancelled = false;
    setSrc("");
    if (path) {
      api
        .readMediaDataUrl(path)
        .then((dataUrl) => {
          if (!cancelled) setSrc(dataUrl);
        })
        .catch(() => {
          if (!cancelled) setSrc("");
        });
    }
    return () => {
      cancelled = true;
    };
  }, [path]);

  return [src, setSrc] as const;
}

function LogList({ logs, compact = false }: { logs: CaptureLog[]; compact?: boolean }) {
  if (logs.length === 0) {
    return <div className="empty-log">暂无日志</div>;
  }
  return (
    <div className={compact ? "logs compact" : "logs"}>
      {logs.map((log, index) => (
        <div className="log-line" key={`${log.stream}-${index}-${log.line}`}>
          <span>{log.stream}</span>
          <code>{log.line}</code>
        </div>
      ))}
    </div>
  );
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function formatTime(ms: number) {
  if (!ms) return "未知时间";
  return new Date(ms).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDimensions(file: MediaFile) {
  if (!file.width || !file.height) return "";
  return `${file.width}x${file.height}`;
}

function filterImagesByAspect(files: MediaFile[], filter: AspectFilter) {
  if (filter === "all") return files;

  return files.filter((file) => {
    if (!file.width || !file.height) return false;

    const ratio = file.width / file.height;
    const near = (target: number) => Math.abs(ratio - target) <= 0.04;

    if (filter === "landscape") return ratio > 1.08;
    if (filter === "portrait") return ratio < 0.92;
    if (filter === "square" || filter === "1:1") return near(1);
    if (filter === "3:4") return near(3 / 4);
    if (filter === "4:3") return near(4 / 3);
    if (filter === "9:16") return near(9 / 16);
    if (filter === "16:9") return near(16 / 9);

    return true;
  });
}

function clampPort(value: number) {
  if (!Number.isFinite(value)) return defaultSettings.port;
  return Math.max(1, Math.min(65535, Math.round(value)));
}
