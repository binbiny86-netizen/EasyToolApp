# 得物 MuMu 采集工具

这是一个面向 MuMu 模拟器的得物图片/视频采集工具。

第一版桌面 App 用 Tauri + React 做界面，底层继续使用 `mitmproxy` 和 Python addon 拦截 MuMu 中得物 App 加载的素材。图片会统一转换为 RGB JPEG，便于 ERP 系统上传；视频会保存到独立目录。

## 当前能力

- 启动/停止采集代理
- 显示 MuMu 需要配置的代理地址
- 保存得物相关域名的图片到 `images/`
- 从得物 JSON API 响应中提取图片 URL 并补充下载
- 保存视频到 `videos/`
- 将图片转换为 RGB JPEG
- 输出结构化 JSON 日志，供桌面 App 展示
- 在桌面 App 中查看素材、日志和基础设置

## 环境要求

开发运行需要：

- Node.js 20+
- npm
- Python 3.9+
- mitmproxy
- Pillow
- pillow-heif
- Rust/Cargo，用于运行或打包 Tauri 桌面 App

新电脑准备顺序：

```powershell
# 1. 安装 Rust/Cargo
winget install Rustlang.Rustup

# 2. 安装 Windows C++ Build Tools
winget install Microsoft.VisualStudio.2022.BuildTools

# 3. 安装 Python 采集依赖
py -m pip install mitmproxy Pillow pillow-heif

# 4. 安装前端依赖并启动
npm.cmd install
npm.cmd run tauri dev
```

如果当前机器没有 `winget`，可以用微软官方安装器：

```powershell
$installer = Join-Path $env:TEMP "vs_BuildTools.exe"
Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vs_BuildTools.exe" -OutFile $installer
& $installer --quiet --wait --norestart --nocache --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended
```

安装 Rust 和 C++ Build Tools 后，建议关闭当前 PowerShell，重新打开再验证：

```powershell
cargo --version
py -m mitmproxy --version
npm.cmd run build
```

如果普通 PowerShell 里还找不到 `cl` 或 `link`，可以从 Visual Studio 开发环境启动：

```powershell
cmd /c "call ""C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\Tools\VsDevCmd.bat"" -arch=x64 && npm.cmd run tauri dev"
```

安装 Python 依赖：

```bash
py -m pip install mitmproxy Pillow pillow-heif
```

如果 `python` 在你的机器上可用，也可以使用：

```bash
python -m pip install mitmproxy Pillow pillow-heif
```

安装前端依赖：

```bash
npm.cmd install
```

PowerShell 如果拦截 `npm` 脚本，使用 `npm.cmd`。

## 开发运行

先启动 Tauri 开发环境：

```bash
npm.cmd run tauri dev
```

如果当前机器还没有安装 Rust/Cargo，可以先只预览前端：

```bash
npm.cmd run dev
```

浏览器预览模式不能启动 mitmproxy，只用于检查界面。

## MuMu 使用流程

1. 打开桌面 App。
2. 在首页或“设置”中确认监听端口、输出目录和 `mitmdump` 命令。默认填 `mitmdump` 即可，App 会优先解析到当前 Python 安装的 `Scripts\mitmdump.exe`，这样 addon 可以使用当前 Python 里的 Pillow。
3. 点击“启动”。
4. 确认 App 处于“采集中”后，在首页点击“设置代理”，App 会通过 MuMu 自带 ADB 写入 Android Wi-Fi 代理：
   - 服务器：App 中显示的本机 IP
   - 端口：App 中显示的监听端口，默认 `8080`
5. 在 MuMu 浏览器访问 `http://mitm.it`。
6. 下载并安装 mitmproxy CA 证书。
7. 打开得物 App，正常浏览商品。
8. 图片和视频会自动出现在 App 的“素材”页面。

如果要恢复 MuMu 网络，点击首页的“清除”按钮即可清除 Android 全局代理。

注意：

- 不要把 MuMu 代理设置到未监听的端口，否则得物所有 API 都会无法访问。
- 不要给 MuMu 设置 `127.0.0.1` 作为代理服务器；这会指向 MuMu 自己，而不是电脑。
- App 会在设置代理前检查目标 `IP:端口` 是否可连接。
- 如果上一次异常退出导致旧的 `dewu_image_saver.py`/`mitmdump` 还占着当前端口，App 会在启动采集时自动清理这个旧采集进程后重试。
- 得物部分商品图会藏在 JSON API 响应里，脚本会解析 JSON 并补充下载这些图片。

## 剪贴板图片识图

如果你已经在电脑上复制了一张图片，可以用脚本一键打开得物识图，并使用得物的“实时截屏”扫描电脑画面：

```powershell
py .\dewu_clipboard_image_search.py
```

默认流程：

1. 在电脑上复制一张要识图的商品图。
2. 确认桌面 App 已经启动采集，并且 MuMu 已设置代理。
3. 回到 PowerShell 运行上面的命令。
4. 脚本会读取 Windows 剪贴板图片，保存到 `clipboard_uploads/`。
5. 脚本会在电脑屏幕上弹出一个置顶图片预览窗口。
6. 脚本会重启得物，自动点击首页搜索框里的识图入口，再点击“实时截屏”。
7. 得物会直接扫描电脑画面，不再依赖 MuMu 相册刷新。

如果得物“实时截屏”的按钮位置变化，可以指定坐标：

```powershell
py .\dewu_clipboard_image_search.py --screen-x 720 --screen-y 1040
```

如果你想继续用原来的相册导入方式：

```powershell
py .\dewu_clipboard_image_search.py --method album
```

相册方式下，如果得物图片选择页没有立即出现新图，可以把等待时间拉长：

```powershell
py .\dewu_clipboard_image_search.py --method album --media-timeout 15
```

相册方式下，如果你想指定导入目录：

```powershell
py .\dewu_clipboard_image_search.py --method album --remote-dir /sdcard/Pictures/DewuSearch
```

如果你已经手动打开到得物图片选择页，只想让脚本导入并点击最新图片：

```powershell
py .\dewu_clipboard_image_search.py --method album --manual-picker
```

如果不想让脚本重启得物：

```powershell
py .\dewu_clipboard_image_search.py --no-restart-dewu
```

如果得物或系统相册布局变化，默认点击位置不对，可以手动指定点选坐标：

```powershell
py .\dewu_clipboard_image_search.py --photo-x 240 --photo-y 620
```

如果得物首页识图入口位置变化，可以指定入口坐标：

```powershell
py .\dewu_clipboard_image_search.py --entry-x 900 --entry-y 180
```

只导入图片、不自动点击：

```powershell
py .\dewu_clipboard_image_search.py --no-tap
```

如果不希望脚本启动得物，只在当前页面找识图入口：

```powershell
py .\dewu_clipboard_image_search.py --no-open-dewu
```

ADB 设置等价命令：

```bash
adb connect 127.0.0.1:7555
adb shell settings put global http_proxy <电脑IP>:<端口>
adb shell settings put global http_proxy :0
```

## 输出说明

默认输出目录由 App 设置决定。输出目录下会创建：

- `images/`：RGB JPEG 图片
- `videos/`：视频文件
- `dewu_requests.log`：调试请求日志

文件名规则：

- URL 的 MD5 前 12 位
- 图片统一使用 `.jpg`
- 视频尽量根据响应类型或 URL 保留扩展名

## 命令行后备方式

不使用桌面 App 时，仍然可以直接运行 mitmproxy：

```bash
D:\Environment\python\Scripts\mitmdump.exe -s dewu_image_saver.py -p 8080
```

把 `8080` 换成你需要的监听端口即可，例如：

```bash
D:\Environment\python\Scripts\mitmdump.exe -s dewu_image_saver.py -p 9090
```

不要使用 mitmproxy 独立二进制直接加载该 addon，除非你能把 Pillow 安装进它自带的 Python 环境。独立二进制会报 `ModuleNotFoundError: No module named 'PIL'`。

可通过环境变量调整采集行为：

```bash
set DEWU_OUTPUT_DIR=D:\captures
set DEWU_DEBUG=1
set DEWU_JPEG_QUALITY=95
set DEWU_HOST_KEYWORDS=dewu,poizon,shihuo,dewucdn,dewuimg,aliyuncs
D:\Environment\python\Scripts\mitmdump.exe -s dewu_image_saver.py -p 8080
```

PowerShell 示例：

```powershell
$env:DEWU_OUTPUT_DIR = "D:\captures"
$env:DEWU_DEBUG = "1"
$env:DEWU_JPEG_QUALITY = "95"
$env:DEWU_HOST_KEYWORDS = "dewu,poizon,shihuo,dewucdn,dewuimg,aliyuncs"
D:\Environment\python\Scripts\mitmdump.exe -s dewu_image_saver.py -p 8080
```

## 常见问题

### App 提示找不到 mitmdump 或 No module named PIL

先安装 mitmproxy：

```bash
py -m pip install mitmproxy
```

然后在 App 设置中使用默认值：

```text
mitmdump
```

### Tauri 运行失败，提示找不到 cargo

安装 Rust：

```bash
winget install Rustlang.Rustup
```

安装后重新打开终端，再运行：

```bash
cargo --version
npm.cmd run tauri dev
```

### MuMu 没有流量或没有图片

- 确认 MuMu 的代理服务器和端口填写正确。
- 确认桌面 App 处于“采集中”。
- 确认 MuMu 已安装并信任 mitmproxy 证书。
- 确认得物请求域名包含设置中的关键词。

### Android 证书限制

不同 Android 版本和 App 可能对用户证书有额外限制。第一版工具不做自动证书安装，也不尝试绕过应用安全策略。后续可以通过 ADB 做 MuMu 检测、打开得物和部分配置引导。
