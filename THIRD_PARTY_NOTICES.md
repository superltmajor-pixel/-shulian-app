# 第三方软件与许可告知

本文件说明第三方组件的许可。数恋自身源码的许可见 [LICENSE](LICENSE) 和 [LICENSING.md](LICENSING.md)；第三方组件保留各自版权与许可，不因项目采用 AGPL 或另行商业授权而改变。

## 随源码分发的前端与字体

- React、React DOM 和 scheduler 的完整版权及 MIT 许可文本随前端产物位于 [THIRD-PARTY-NOTICES.txt](web/bundle/THIRD-PARTY-NOTICES.txt)。
- `npm run build:web` 从实际安装的软件包重新生成上述告知；`npm run check:web` 校验内容及哈希。升级依赖后必须重新构建并提交告知文件。
- Noto Sans SC 的许可证位于 [LICENSE-NotoCJK.txt](web/fonts/LICENSE-NotoCJK.txt)。
- 两份 PyInstaller 配置均允许收集上述 `.txt` 文件，因此告知文件与前端资源一起进入后续构建的客户端。

## Python 与桌面运行依赖

两份 PyInstaller 配置调用 `binary_notices.py`，根据本次实际选入的 Python 模块及本地扩展自动收集已安装发行包的许可/版权/NOTICE 文件。产物中的 `_internal/third-party/manifest.json` 记录版本、许可文件及 SHA-256，不包含构建机器的绝对路径。Python 解释器许可也随包保留。

`edge-tts` 和 `certifi` 的实际 Python 源文件随各自告知保留；公开二进制还应同时提供对应的完整上游源码归档、应用源码及重建说明，见 [便携包构建与验收](docs/portable-release.md)。这份自动清单不代替本地 DLL 和嵌入组件的许可核对。

源码通过 requirements.txt 声明运行依赖；桌面运行另需 pywebview、pythonnet，打包使用 PyInstaller。以下是准备二进制发布时应核对的主要许可，不能统一替换为项目自身许可证：

| 组件 | 许可依据 |
| --- | --- |
| FastAPI、Pydantic | MIT |
| Uvicorn、pywebview | BSD-3-Clause |
| OpenAI Python SDK、sherpa-onnx | Apache-2.0 |
| edge-tts 7.2.3 | srt_composer.py 使用 MIT，其余文件 LGPLv3，见其发行包 LICENSE |
| NumPy | BSD-3-Clause 及发行包内附带的其他第三方许可 |
| PyInstaller | GPL 及项目规定的打包例外，见其 COPYING.txt |

上表不是完整的二进制依赖清单，也不取代任何上游许可证。公开分发 EXE/更新包前，应根据最终产物核对所有实际包含的直接/间接依赖、版权告知，以及适用的源码提供等义务。不要把仅提供服务接口的 GPT-SoVITS 服务或用户自行下载的模型视为已经随源码分发；若未来捆绑这些组件，需另行核对。

角色、图片、声音、用户配置和聊天属于本地用户数据，不包含在本项目源码授权中。导入第三方内容不会自动取得其公开再分发权利。
