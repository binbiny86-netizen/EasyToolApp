# macOS 运行说明

这个项目可以在 macOS 上运行同一套 Tauri 桌面界面和 mitmproxy 采集逻辑。macOS 上仍然需要 MuMu、得物 App、Python 采集依赖和 mitmproxy 证书。

## 环境准备

```bash
xcode-select --install
brew install node
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
python3 -m pip install mitmproxy Pillow pillow-heif
```

验证：

```bash
node -v
npm -v
cargo --version
python3 -m mitmproxy --version
```

## MuMu ADB

App 会尝试从 `/Applications`、`~/Applications`、常见 MuMu app bundle 和 `PATH` 里自动查找 `adb`。如果没有找到，可以手动指定：

```bash
export MUMU_ADB=/path/to/adb
npm run tauri dev
```

MuMu 代理仍然使用电脑局域网 IP 和 App 里的监听端口。不要把 MuMu 的代理服务器填成 `127.0.0.1`，那会指向模拟器自己。

## 启动

```bash
npm install
npm run tauri dev
```

如果 `mitmdump` 不在 GUI App 的 PATH 中，可以在设置页把 `mitmdump 命令` 改成完整路径，例如：

```text
/opt/homebrew/bin/mitmdump
```

或：

```text
/usr/local/bin/mitmdump
```

## 打包

macOS 安装包需要在 Mac 上构建：

```bash
npm run tauri build
```

未签名的本地包第一次打开时可能需要在系统设置里允许打开。正式分发给其他 Mac 使用时，建议后续再补 Apple Developer 签名和公证流程。
