# 语音通话（正式版 0.25.27）

语音和视频通话提供两条可选线路。默认“兼容模式”复用已经配置好的聊天大模型与 Edge TTS / GPT-SoVITS，不要求额外开通豆包语音；“豆包端到端”使用 SC 2.0（`dialog.extra.model=2.2.0.0`），提供持续全双工收音与说话打断。

## 兼容模式

1. 进入语音或视频通话页后直接选择“兼容模式”接通，不需要填写新的 API Key。它复用数恋当前登录的聊天服务和原有 `/api/tts/{character_id}` 朗读链路。
2. 正式桌面客户端使用本地流式中文识别。首次使用点击“下载本地中文语音模型”（约 25 MB）；模型保存在 `%LOCALAPPDATA%\Shulian\models`，只在本机运行。识别到一句完整的话后，文本才会发送给现有聊天服务；再由 GPT-SoVITS（已配置时）或 Edge TTS 朗读，朗读结束后自动恢复收音。
3. 普通浏览器仍尝试使用浏览器语音识别。桌面端录音音频不会上传给语音识别云服务；发送聊天文本、调用已有 TTS 时仍遵循各自服务的网络与计费规则。
4. 这是自动轮流说话，不是全双工流式模型。角色生成或朗读期间不会持续识别环境声音，以避免把扬声器回声当成用户输入；需要真正的边说边听和自然打断时切换豆包端到端。
5. 模型尚未下载或本地识别组件不可用时，通话仍可接通并使用文字输入；桌面端会给出明确的模型准备/客户端版本提示，不再依赖 WebView 的云端语音识别服务。普通浏览器的临时识别错误会按 1、2、4、8 秒退避重试；连续失败 5 次后暂停。挂断后仍只在聊天记录中保存一条通话小结，已完成的通话轮次进入原有记忆流程。

## 豆包端到端配置和使用

1. 在火山引擎豆包语音控制台开通端到端实时语音服务，取得该服务的 App ID 和 Access Token；文字聊天 Key 不能替代此处凭据。
2. 进入角色的语音通话页，选择“豆包端到端”，填写凭据及当前角色音色 ID。默认 `saturn_zh_female_wenrouwenya_tob`；SC 2.0 使用匹配版本的 `saturn_` 公版音色或已授权开通的 `S_` 复刻音色。
3. 保存配置只写本机加密文件，不验证云端权限，也不产生语音调用。修改音色时可留空 Token 保留旧值；更换 App ID 必须重新填写 Token，并会清除旧应用下的角色音色映射，避免复用不属于新应用的 `S_` 复刻音色。
4. 点击“连接实时通话”并允许麦克风。连接成功后持续上传音频，服务按用量计费。说话结束由服务端判断；角色说话时可直接开口打断。
5. 麦克风按钮切换静音，扬声器按钮关闭/开启播放。挂断、断线、权限失败或音频堆积均释放麦克风、播放队列和连接。断线后在原页面手动重连，保留本次已经确认的对话内容，不重发音频。

凭据使用现有 Windows DPAPI 存储能力，独立保存于聊天凭据同目录的 `formal-realtime-voice.bin`（默认 `%LOCALAPPDATA%\Shulian`），不写 `.env`、浏览器存储、日志或发布包。音色按角色分别保存。浏览器只访问本机网关，网关只连接固定官方域名。

## 链路和边界

- `web/realtime-audio-worklet.js`：真实麦克风音频转换为 16 kHz、单声道、PCM16LE，每 20 ms 发送一帧；启用浏览器回声消除、降噪、自动增益请求。
- `web/realtime-voice.jsx`：持续收音、24 kHz PCM16 流式播放、字幕、静音、打断、播放进度和会话资源生命周期。
- `web/compatible-voice.jsx`：现有聊天模型 + TTS 的自动轮流通话状态机；桌面端通过本机 WebSocket 将 PCM 帧送入离线识别，普通浏览器使用浏览器语音识别；管理服务端 TTS、浏览器朗读兜底、恢复收音和挂断清理。
- `shulian_backend/routers/local_asr.py`、`shulian_backend/services/local_asr.py`：同源本机语音 WebSocket、模型首次下载、路径/体积/文件清单校验，以及 sherpa-onnx 中文流式识别。模型和录音数据不进入发布包或日志。
- `shulian_backend/routers/realtime_voice.py`：同源且限本机的配置 API / WebSocket、双向转发、超时、数据限额和结束握手。无云端自动重试，避免重复请求/音频。单次会话上限一小时。
- `shulian_backend/services/realtime_protocol.py`：官方二进制事件协议；处理连接 ID、会话 ID、可选序号、压缩和音频。
- `shulian_backend/services/realtime_voice.py`：加密配置及已有角色、人格、关系、状态和记忆上下文编译。历史只以完整 QA 对传入，初始上下文设 6,000 字符保守预算，为供应商 12K token 上下文留出余量；超长人格规则明确报错，不静默截掉身份/关系规则。字符预算不等于精确 token 计数。

打断由服务端 `ASRInfo (450)` 触发：立即停止本地播放并清理旧帧；通过 `ConversationTruncate (513)` 同步已播放毫秒数。迟到的旧 question/reply 事件不会重新开启播放。只将完整播放完的句子写入本地通话记忆；中途打断的半句话不推测转写。字幕展示生成文本，可能领先播放。

豆包端到端线路直接生成音频与文字，不调用原文本聊天模型；它复用角色上下文，但不经过原文本模型的生成后纠错/重生成流程。兼容模式则完整复用原聊天模型的角色、记忆、状态和安全边界。视频通话复用所选语音线路，摄像头仍为本地画面，不向语音服务发送视频。实际回声消除、角色一致性、音色权限和网络延迟须在正式客户端中验收。

本地流式识别运行时使用官方 sherpa-onnx Python CPU wheel 和中文 14M Zipformer 模型；模型文件清单与输入格式见 [sherpa-onnx 在线 Zipformer 中文模型说明](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html) 及 [Python 安装说明](https://k2-fsa.github.io/sherpa/onnx/python/install.html)。

## 验证

- `node --test tests/realtime-voice.test.mjs`：音频帧、重采样、静音、打断、旧回复过滤、超时、迟到权限及挂断清理。
- `node --test tests/compatible-voice.test.mjs`：兼容模式识别、聊天/TTS 串联、自动恢复收音、静音、浏览器朗读兜底、无识别环境和迟到回复清理。
- `tests.test_realtime_voice`：二进制协议、DPAPI、上下文、来源校验、模拟上游握手/音频/结束流程；包含上述 Node 测试。
- 新依赖 `numpy` / `sherpa-onnx` 已纳入 requirements 和两份 PyInstaller 规格；模型权重首次由用户从官方 sherpa-onnx release 下载至本机数据目录，不打入应用。源码完成不代表模型、EXE 或客户端已更新；本轮不执行打包。
- 本轮没有使用用户凭据发起付费通话。首次实测需在已开通服务后进行，不能用离线模拟结果替代云端/正式客户端验收。

协议依据：[火山引擎端到端实时语音 API 文档](https://docs.volcengine.com/docs/DoubaoVoice/End-to-endreal-timespeechlargemodelAPIaccessdocument?lang=zh)。
