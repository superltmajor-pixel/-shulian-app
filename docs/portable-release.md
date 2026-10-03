# Windows 便携候选包构建与验收

当前版本为 0.26.0 公开测试候选。候选包验收与正式发布分开；尚未发布时保留 `publicReleaseReady=false`，不要把候选 EXE 宣称为已发布的正式下载。

## 从独立干净源码构建

1. 使用 `scripts/export-public-source.py --destination <新目录>` 导出没有旧历史的源码。目标必须为空且与开发目录分离。
2. 在候选目录用 Python 3.14.5 创建虚拟环境，并安装 `requirements-release.txt` 中本候选锁定的依赖。前端使用 `npm ci`、`npm run build:web`、`npm run check:web`。
3. 运行 `python scripts/check-quality.py --verbose`；不要把个人 API Key 或运行数据放入候选目录。
4. 在候选目录执行以下命令，输出路径应为新的专用目录，不能指向已安装的程序：

   ```powershell
   python -m PyInstaller --noconfirm --distpath <新输出目录>/dist --workpath <新输出目录>/build shulian-onedir.spec
   ```

5. 完整归档 `dist/Shulian`，保持 `Shulian.exe` 与 `_internal` 在同一目录。同时保留使用说明、应用源码 ZIP、第三方对应源码、SHA-256 及构建/验收报告。不得从已运行的目录或个人数据目录反向制作发布包。

依赖告知由 `binary_notices.py` 根据本次 Analysis 收集；缺少告知或出现新本地库时，应先核对来源及许可。`packaging/notices/proxy-tools.txt` 是原始 wheel 缺失的上游 BSD 许可；来源为 <https://github.com/jtushman/proxy_tools/blob/master/LICENSE.txt>。`sherpa-onnx-core.txt` 与同版本 sherpa-onnx wheel 中的 Apache 许可一致；`GPL-3.0.txt` 来自 SPDX 对标准 GPL-3.0-only 的原文镜像。

`edge-tts` 7.2.3 的大部分源码采用 LGPLv3（SRT 部分采用 MIT），具体范围见随包 LICENSE。公开分发时同步提供精确版本的源代码归档和 GPL/LGPL 文本，以及本应用源码、依赖锁定表和 PyInstaller 重建步骤，使接收者可以修改库后重新构建。不得限制依法修改相关库及调试该修改所需的逆向工程。`certifi` 的 MPL 告知、源码和证书数据也须保留。

## 离线 EXE 验收

退出其他数恋窗口后运行：

```powershell
python scripts/check-portable-startup.py --app-dir <新输出目录>/dist/Shulian --work-dir <新的验收目录>
```

脚本仅使用新建的合成数据，不读取原客户端数据或凭据，也不调用 AI/语音服务。它检查实际 EXE 启动、空角色库、前端资源、自建角色、图片、导入聊天、编辑和更换程序目录后的数据保留，并按更新说明复制合成的应用目录数据。报告保存为 `acceptance.json`。

此检查不覆盖真实麦克风、上游聊天/语音、原生窗口交互、不同历史版本的数据迁移或自定义路径组合。退出后的验收目录仅为测试证据，不得加入发布 ZIP。

## 发布前

核对本地 DLL 及其嵌入组件（包括 WebView2 SDK、ONNX Runtime、NumPy 本地库与微软运行时）的实际版本、许可和再分发条件；自动收集 Python wheel 许可不表示这些事项已全部通过。创建正式发布时再启用下载入口，冻结相同版本的源码/Build ID，重建产物并核对哈希，不手工修补旧 ZIP 或已安装的 `_internal`。
