import { convertFileSrc, invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";

export type CaptureConfig = {
  port: number;
  outputRoot: string;
  debugMode: boolean;
  jpegQuality: number;
  hostKeywords: string[];
  mitmdumpCommand?: string;
};

export type CaptureStatus = {
  running: boolean;
};

export type MediaFile = {
  name: string;
  path: string;
  kind: "image" | "video";
  bytes: number;
  modifiedMs: number;
  width?: number;
  height?: number;
};

export type MediaList = {
  images: MediaFile[];
  videos: MediaFile[];
};

export type CaptureLog = {
  stream: string;
  line: string;
};

export type AdbInfo = {
  adbPath?: string;
  devices: string[];
  candidatePorts: number[];
};

export type AdbProxyResult = {
  adbPath: string;
  device: string;
  proxy: string;
  output: string;
};

export type EasyToolSettings = {
  baseUrl: string;
  username: string;
  password: string;
  token: string;
  productId: string;
};

export type EasyToolLoginData = {
  id?: number;
  username?: string;
  displayName?: string;
  menuPermissions?: string[];
  token: string;
  expiresAt?: string;
};

export type EasyToolUploadData = {
  productId: number;
  aiReferenceImages: unknown[];
  uploadedImages: unknown[];
  video?: string;
  addedImageCount?: number;
  videoUpdated?: boolean;
};


declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export const isTauri = () =>
  typeof window !== "undefined" && Boolean(window.__TAURI_INTERNALS__);

export const api = {
  async getCaptureStatus(): Promise<CaptureStatus> {
    if (!isTauri()) return { running: false };
    return invoke<CaptureStatus>("get_capture_status");
  },

  async startCapture(config: CaptureConfig): Promise<CaptureStatus> {
    if (!isTauri()) {
      throw new Error("当前是浏览器预览模式，请在 Tauri 桌面窗口中启动采集。");
    }
    return invoke<CaptureStatus>("start_capture", { config });
  },

  async stopCapture(): Promise<CaptureStatus> {
    if (!isTauri()) return { running: false };
    return invoke<CaptureStatus>("stop_capture");
  },

  async getLocalIps(): Promise<string[]> {
    if (!isTauri()) return ["127.0.0.1"];
    return invoke<string[]>("get_local_ips");
  },

  async listMedia(outputRoot: string): Promise<MediaList> {
    if (!isTauri()) return { images: [], videos: [] };
    return invoke<MediaList>("list_media", { outputRoot });
  },

  async deleteFile(path: string): Promise<void> {
    if (!isTauri()) return;
    return invoke<void>("delete_file", { path });
  },

  async readMediaDataUrl(path: string): Promise<string> {
    if (!isTauri()) return "";
    return invoke<string>("read_media_data_url", { path });
  },

  mediaFileSrc(path: string): string {
    if (!isTauri() || !path) return "";
    return convertFileSrc(path);
  },

  async clearMedia(outputRoot: string, kind: "image" | "video" | "all"): Promise<void> {
    if (!isTauri()) return;
    return invoke<void>("clear_media", { outputRoot, kind });
  },

  async openPath(path: string): Promise<void> {
    if (!isTauri()) return;
    return invoke<void>("open_path", { path });
  },


  async detectMumuAdb(): Promise<AdbInfo> {
    if (!isTauri()) {
      throw new Error("当前是浏览器预览模式，请在 Tauri 桌面窗口中检测 MuMu。");
    }
    return invoke<AdbInfo>("detect_mumu_adb");
  },

  async setMumuWifiProxy(
    proxyHost: string,
    proxyPort: number,
    adbPath?: string,
  ): Promise<AdbProxyResult> {
    if (!isTauri()) {
      throw new Error("当前是浏览器预览模式，请在 Tauri 桌面窗口中设置 MuMu 代理。");
    }
    return invoke<AdbProxyResult>("set_mumu_wifi_proxy", {
      proxyHost,
      proxyPort,
      adbPath,
    });
  },

  async clearMumuWifiProxy(adbPath?: string): Promise<AdbProxyResult> {
    if (!isTauri()) {
      throw new Error("当前是浏览器预览模式，请在 Tauri 桌面窗口中清除 MuMu 代理。");
    }
    return invoke<AdbProxyResult>("clear_mumu_wifi_proxy", { adbPath });
  },

  async easyToolLogin(
    baseUrl: string,
    username: string,
    password: string,
  ): Promise<EasyToolLoginData> {
    if (!isTauri()) {
      throw new Error("当前是浏览器预览模式，请在 Tauri 桌面窗口中登录 EasyTool。");
    }
    return invoke<EasyToolLoginData>("easytool_login", {
      baseUrl,
      username,
      password,
    });
  },

  async uploadEasyToolPersonalMedia(
    baseUrl: string,
    token: string,
    productId: number,
    imagePaths: string[],
    videoPath?: string,
  ): Promise<EasyToolUploadData> {
    if (!isTauri()) {
      throw new Error("当前是浏览器预览模式，请在 Tauri 桌面窗口中上传 EasyTool 素材。");
    }
    return invoke<EasyToolUploadData>("easytool_upload_personal_media", {
      baseUrl,
      token,
      productId,
      imagePaths,
      videoPath,
    });
  },

  onCaptureLog(handler: (log: CaptureLog) => void) {
    if (!isTauri()) return Promise.resolve(() => undefined);
    return listen<CaptureLog>("capture-log", (event) => handler(event.payload));
  },
};
