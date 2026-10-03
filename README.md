# 数恋（Shulian）

[简体中文](README.md) | [English](README.en.md)

数恋是一个 Windows 本地优先的数字恋人桌面应用。项目将 FastAPI 后端、React 前端和 pywebview 桌面外壳打包为独立客户端，并提供角色陪伴、流式聊天、关系记忆、语音合成和本地角色档案等能力。

角色内容与程序代码分开保存。新安装不附带角色，在应用的“恋人”页创建或导入。
个人角色、人设、图片与聊天不随源码或更新包分发，详见 [本地角色与公开源码](docs/local-character-data.md)。

## 功能概览

- 应用内创建、编辑、导入和管理本地角色
- 可配置 AI 服务、流式对话与上下文记忆
- 亲密度、关系约定、历史会话和角色档案
- Edge TTS 与 GPT-SoVITS 语音合成
- 深色、浅色和跟随系统主题
- Windows 原生桌面窗口与持久化本地数据
- API Key 加密保存，不随源码或安装包分发
- 性能模式：降低玻璃模糊，窗口处于后台时暂停氛围动画

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.14、FastAPI、Uvicorn、Pydantic |
| AI | OpenAI Python SDK、DeepSeek API |
| 前端 | React 18、JSX/CSS、Vite 本地构建 |
| 桌面端 | pywebview、Microsoft Edge WebView2 |
| 语音 | edge-tts、GPT-SoVITS |
| 打包 | PyInstaller onedir |
| 测试 | Python `unittest` |

## 项目结构

```text
shulian-backend/
├─ main.py                     # FastAPI 应用、接口与静态资源入口
├─ desktop.py                  # 桌面窗口、后端启动和单实例控制
├─ chat.py                     # AI 对话与提示词组装
├─ characters.py               # 通用角色模型
├─ role_content.py             # 本地角色专属配置读取
├─ status_engine.py            # 角色状态与日程
├─ ai_credentials.py           # API Key 验证与本机加密存储
├─ role_archive.py             # 角色档案和快照
├─ web/                        # 通用 React 前端和样式
├─ tests/                      # 自动化回归测试
├─ docs/                       # 项目补充文档
├─ requirements.txt            # 后端运行依赖
├─ .env.example                # 非敏感运行配置示例
├─ shulian-onedir.spec         # 正式桌面版 PyInstaller 配置
├─ package-shulian-inplace.ps1 # 正式客户端原位更新脚本
└─ start.bat                   # 浏览器开发模式启动入口
```

`build/`、`dist/`、`venv/`、日志、用户媒体和本机 `.env` 均属于生成物或本地状态，不应提交到版本库。

## 快速开始

### 1. 准备环境

推荐使用 Windows 10/11 和 Python 3.14。当前前端构建支持 Node.js 20.19.x 及更新的 20.x，或 Node.js 22.12 及以上版本，并需要 npm。

前端通过 Vite 构建为本地 bundle，运行时不依赖 CDN。修改前端后执行 `npm ci`、`npm run build:web` 和 `npm run check:web`。

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

桌面运行和打包环境还需要安装：

```powershell
.\venv\Scripts\python.exe -m pip install pywebview pyinstaller pythonnet
```

### 2. 配置运行参数

复制 `.env.example` 为 `.env`，按需填写模型、超时和 TTS 配置。

```powershell
Copy-Item .env.example .env
```

API Key 不写入 `.env`。首次启动客户端后，在 AI 连接界面配置；验证成功后使用 Windows DPAPI 加密保存。

### 3. 启动开发环境

浏览器开发模式：

```powershell
.\start.bat
```

- 应用：<http://127.0.0.1:8000/>
- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/health>

桌面开发模式：

```powershell
.\venv\Scripts\python.exe .\desktop.py
```

桌面端固定使用 `127.0.0.1:8770`，并执行单实例与端口占用检查。

## 测试

运行完整离线回归测试（自动隔离角色、聊天状态和凭据路径，并阻止外部服务连接）：

```powershell
.\venv\Scripts\python.exe scripts/check-quality.py --verbose
```

运行关键 Python 文件的语法检查：

```powershell
.\venv\Scripts\python.exe -m py_compile main.py chat.py desktop.py
```

测试数量随功能增长，以本次命令的实际结果为准。不要用跳过失败或直接连接个人运行数据的方式验收。

## 打包与发布

普通用户的下载与数据保留步骤见 [公开测试版更新说明](docs/public-updates.md)。首个公开包尚在准备中；当前更新入口不会自动检查、下载或安装 GitHub 上的新版本。

在源码目录配置打包路径后运行脚本。下面的路径仅为示例，应替换成自己的源码与客户端目录：

```powershell
$env:SHULIAN_REPO = (Get-Location).Path
$env:SHULIAN_APP_DIR = 'C:\Apps\Shulian\dist'
pwsh -NoProfile -File .\package-shulian-inplace.ps1
```

也可在脚本同目录创建本地 `packager.local.json`，设置 `repo`、`appDir` 两个绝对路径；该文件已被 Git 忽略。脚本使用 `shulian-onedir.spec`，执行离线检查与前端构建，生成发布产物并原位更新指定客户端，可能关闭并重新启动应用。只有准备执行实际更新时才运行。

发布时必须分别确认以下状态：

1. `code modified`：源码已修改。
2. `resources synced`：前端资源和打包脚本已同步。
3. `EXE packaged`：正式 EXE 已重新生成。
4. `client verified`：安装目录中的客户端已实际启动并验证。

不要把“源码测试通过”等同于“正式客户端已经更新”。

## 数据与配置

正式客户端的数据边界如下：

| 路径 | 内容 | 更新客户端时的处理 |
| --- | --- | --- |
| `%LOCALAPPDATA%\Shulian\role-library` | 本地角色档案及资源 | 必须保留 |
| `%LOCALAPPDATA%\Shulian\data\shulian.sqlite3` | 聊天、关系及应用状态主存储 | 必须保留 |
| `dist\webview-data` | Local Storage、登录状态、WebView 缓存 | 必须保留 |
| `dist\media` | 用户语音和媒体文件 | 必须保留 |
| `dist\.env` | 模型、超时、TTS 等非敏感配置 | 必须保留 |
| `dist\_internal` | Python 运行时与只读前端资源 | 可由新包替换 |
| `dist\Shulian.exe` | 桌面程序入口 | 可由新包替换 |

API Key 由客户端凭据模块加密管理，不得硬编码、写入仓库或打进 `_internal\.env`。
以上为默认位置；`SHULIAN_ROLE_LIBRARY_DIR`、`SHULIAN_STATE_DB` 等环境变量可覆盖相应路径。

## 运行诊断

正式客户端启动后可检查：

```text
http://127.0.0.1:8770/health
http://127.0.0.1:8770/api/self-check
```

打包客户端默认在 `Shulian.exe` 同目录写入 `shulian-debug.log`，源码模式默认在源码目录写入。设置 `SHULIAN_LOG_DIR` 可覆盖此位置。

常见问题：

- `8770` 被占用：关闭旧的数恋进程或占用该端口的程序后重试。
- 窗口打开但页面未渲染：执行前端构建检查，确认本地 bundle 存在且与源码一致。
- 前端仍是旧页面：确认缓存版本号、打包脚本副本和正式包资源是否一致。
- 更新后数据消失：立即停止覆盖，检查是否误删了 `webview-data`、`media` 或 `.env`。
- TTS 不工作：检查 `.env` 中的 `TTS_PROVIDER` 和 GPT-SoVITS 服务地址。

## 当前版本

- 版本与构建标识：以 `release.json` 为准；源码与已安装客户端应分别核验。
- 桌面端口：`8770`
- 开发端口：`8000`
- 内置角色：0；角色全部来自本地档案。

## 贡献与版本管理

- 功能修改应附带或更新相应测试。
- 前端资源变更时，应同步更新 `web/index.html` 的缓存版本号。
- 不要提交 `.env`、API Key、用户媒体、WebView 数据或构建目录。
- 保留与本次任务无关的工作区修改，禁止用破坏性 Git 命令清理他人改动。
- 正式发布前应记录构建标识、测试结果、包体积、数据保留检查和回滚位置。

## 许可证

本项目自行拥有或有权按本许可发布的源码及配套文档采用 **GNU Affero General Public License v3.0 only（AGPL-3.0-only）**，完整条款见 [LICENSE](LICENSE)，适用范围见 [LICENSING.md](LICENSING.md)。

AGPL 允许商业使用、收费与再分发；应遵守其对应源码、许可告知及适用的网络交互义务。需要不同于 AGPL 的闭源集成等授权，可按 [商业授权说明](COMMERCIAL_LICENSE.md) 单独协商；商业使用本身不要求购买授权。

个人角色、人设、图片、音频、聊天记录及本机配置不因使用本软件而取得开源授权，也不随源码分发。第三方组件遵循各自许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

- 品牌与名称使用：[TRADEMARKS.md](TRADEMARKS.md)。
- 提交贡献：[CONTRIBUTING.md](CONTRIBUTING.md)；涉及代码或文档贡献时，合并前需按 [CLA.md](CLA.md) 完成贡献授权。
