# 🎙️ AI Voice Sales

> 基于 LiveKit 的实时语音 Agent 工程。
>
> 当前建议的阅读顺序是：
>
> 1. 先部署 `LiveKit Server`
> 2. 再按本文的 **Online 版从零启动** 跑通整条链路
> 3. 最后再看 `Local` 自部署模式和模型部署

---

## 1️⃣ 最重要的前提

无论你使用 `Online` 版本还是 `Local` 版本，**都必须先有一个可用的 `LiveKit Server`**。

没有 `LiveKit Server`：

- Agent 不能加入房间
- 前端不能发起测试会话
- 后面的 `ASR / LLM / TTS` 都没有接入入口

`LiveKit Server` 部署文档：

- [`docs/LiveKit-Server部署.md`](./docs/LiveKit-Server部署.md)

---

## 2️⃣ 推荐使用方式

当前仓库有两种运行方式：

### 🌐 Online 版

这是**默认推荐**的方式，也是本文重点。

特点：

- 更适合从零开始
- 更容易先跑通整条链路
- 不要求你先自己部署整套模型服务

适用场景：

- 演示环境
- 测试环境
- 初次部署
- 先验证 Agent 是否正常工作

### ⚙️ Local 版

这是**进阶模式**，目标是更低延迟和更强控制权。

特点：

- 不是开箱即用
- 不能直接跑通
- 需要先部署自己的模型服务
- **需要额外测试和调参**

适用场景：

- 你已经跑通 Online 版
- 你要做自部署模型链路
- 你要优化延迟、中断、VAD、endpointing

---

## 3️⃣ Online 版从零启动

这一节是主线流程。**建议先只看这一节，先把系统跑起来。**

### 3.1 先准备 LiveKit Server

先部署并确认 `LiveKit Server` 可用。

需要准备：

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`

参考文档：

- [`docs/LiveKit-Server部署.md`](./docs/LiveKit-Server部署.md)

### 3.2 再准备前端

如果你使用 `uv run src/agent_Online.py dev` 或 `uv run src/agent_Local.py dev` 这种方式启动 Agent，**还需要一个前端页面来发起测试会话**。

当前测试环境默认前端是：

- `livekit-agent-ui`

这个前端需要你**自行部署**，并把部署后的访问地址填到你自己的测试记录或环境说明里。

你可以在 README 或自己的部署文档里补上类似信息：

```text
测试前端地址：
https://your-livekit-agent-ui.example.com
```

如果没有前端页面，即使 Agent 进程已经启动，也不代表你能完整验证语音对话链路。

### 3.3 配置 Online 版环境变量

`Online` 版实际需要这些变量：

```env
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

VOLCENGINE_STT_APP_ID=
VOLCENGINE_STT_ACCESS_TOKEN=
VOLCENGINE_BIGMODEL_STT_MODEL=bigmodel

DASHSCOPE_API_KEY=
MINIMAX_API_KEY=
```

说明：

- STT 当前走火山
- LLM 当前走 DashScope 兼容接口
- TTS 当前走 MiniMax

环境变量模板见：

- [`.env.example`](./.env.example)

### 3.4 安装依赖

```bash
uv sync
```

### 3.5 启动 Online 版 Agent

```bash
uv run src/agent_Online.py dev
```

### 3.6 Online 版最小检查清单

确认以下几项：

1. `LiveKit Server` 可用
2. 前端 `livekit-agent-ui` 可访问
3. Agent 已启动
4. 火山 STT 密钥正确
5. DashScope 密钥正确
6. MiniMax 密钥正确

如果你要的是“先跑通”，这一节就足够了。

---

## 4️⃣ 当前代码里的组件状态

### Online 版当前默认链路

- STT: 火山 `BigModelSTT`
- LLM: DashScope 兼容接口
- TTS: MiniMax

入口文件：

- [`src/agent_Online.py`](./src/agent_Online.py)

### Local 版当前默认链路

- STT: `QwenStreamingSTT` + 自部署 Qwen ASR WebSocket 服务
- LLM: 自部署 `qwen2.5-7b-instruct` OpenAI 兼容接口
- TTS: 当前代码里默认仍是 MiniMax

入口文件：

- [`src/agent_Local.py`](./src/agent_Local.py)

另外，仓库里已经有独立的 Qwen TTS 服务：

- [`qwen-tts-service/server.py`](./qwen-tts-service/server.py)
- [`qwen-tts-service/README.md`](./qwen-tts-service/README.md)

但它**还没有正式接入当前 agent 的默认 TTS 链路**。

---

## 5️⃣ Local 版说明

这一节是进阶内容，不建议第一次就从这里开始。

### 5.1 Local 版是什么

`Local` 版不是“更适合开发”的意思，而是：

- 更偏向低延迟
- 更偏向自部署
- 更偏向自己掌控整条推理链路

### 5.2 Local 版为什么不能直接跑

因为它依赖你先准备好这些服务：

- `LiveKit Server`
- `Qwen ASR` 服务
- `Qwen2.5-7B-Instruct` 的 vLLM 服务
- 如果后续切 Qwen TTS，还要准备 `Qwen3-TTS` 服务

相关参考：

- [`docs/LLM部署.md`](./docs/LLM部署.md)
- [`qwen-asr-streaming-service/README.md`](./qwen-asr-streaming-service/README.md)
- [`qwen-tts-service/README.md`](./qwen-tts-service/README.md)

而且你通常还需要继续调：

- `ALLOW_INTERRUPTIONS`
- `PREEMPTIVE_GENERATION`
- `RESUME_FALSE_INTERRUPTION`
- `MIN_INTERRUPTION_DURATION`
- `MIN_ENDPOINTING_DELAY`
- `MAX_ENDPOINTING_DELAY`
- VAD / 中断 / endpointing 相关效果

还需要明确一点：

- `Local` 不是把服务启动起来就结束
- **还需要做真实语音测试**
- **还需要根据测试结果反复调参**
- **还需要持续对比延迟、中断效果、识别稳定性**

### 5.3 Local 版环境变量

```env
LIVEKIT_URL=
LIVEKIT_API_KEY=
LIVEKIT_API_SECRET=

QWEN_STREAMING_STT_WS_URL=ws://127.0.0.1:8001/ws
QWEN_STREAMING_STT_MODEL=qwen3-asr-streaming

LLM_MODEL=qwen2.5-7b-instruct
LLM_BASE_URL=http://127.0.0.1:8000/v1
LLM_API_KEY=fake-key

MINIMAX_API_KEY=

ALLOW_INTERRUPTIONS=false
PREEMPTIVE_GENERATION=false
RESUME_FALSE_INTERRUPTION=false
MIN_INTERRUPTION_DURATION=0.45
MIN_ENDPOINTING_DELAY=0.0
MAX_ENDPOINTING_DELAY=0.05
```

### 5.4 Local 版启动入口

```bash
uv run src/agent_Local.py dev
```

启动前至少要保证：

- `LIVEKIT_URL` 可用
- `QWEN_STREAMING_STT_WS_URL` 可连通
- `LLM_BASE_URL` 可连通
- 如果后续切 Qwen TTS，还要保证 TTS 服务可连通
- 前端 `livekit-agent-ui` 可访问

---

## 6️⃣ 模型与服务部署

这一节同样属于进阶内容，建议在 Online 版跑通之后再看。

### 6.1 推荐自部署模型组合

| 组件 | 模型 | 推荐部署位置 | 说明 |
| :--- | :--- | :--- | :--- |
| ASR | `qwen-asr` | GPU 服务器 | 实时流式识别 |
| LLM | `qwen2.5-7b-instruct` | GPU 服务器 | vLLM OpenAI 兼容接口 |
| TTS | `Qwen3-TTS-12Hz-1.7B-CustomVoice` | GPU 服务器 | 当前推荐原生 `qwen-tts` Python 服务 |

### 6.2 哪些放 GPU，哪些放普通服务器

GPU 服务器建议运行：

- `qwen-asr-streaming-service`
- `qwen2.5-7b-instruct` + `vLLM`
- `qwen-tts-service`

普通服务器建议运行：

- `LiveKit Server`
- `Agent`
- `Nginx / 反向代理`

### 6.3 GPU 服务启动参考

更多说明见：

- [`docs/LLM部署.md`](./docs/LLM部署.md)
- [`qwen-asr-streaming-service/README.md`](./qwen-asr-streaming-service/README.md)
- [`qwen-tts-service/README.md`](./qwen-tts-service/README.md)

Qwen2.5-7B-Instruct：

```bash
python -m vllm.entrypoints.openai.api_server \
  --model /path/to/Qwen2.5-7B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --dtype bfloat16 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --tensor-parallel-size 1
```

Qwen ASR：

```bash
uv sync --group asr_service
uv run qwen-asr-streaming-service/server.py \
  --model /path/to/qwen-asr \
  --host 0.0.0.0 \
  --port 8001 \
  --gpu-memory-utilization 0.8 \
  --max-new-tokens 32
```

Qwen TTS：

```bash
uv sync --group tts_service
uv run qwen-tts-service/server.py \
  --model /path/to/Qwen3-TTS-12Hz-1.7B-CustomVoice \
  --host 0.0.0.0 \
  --port 8091 \
  --device-map cuda:0 \
  --dtype bfloat16 \
  --default-speaker Vivian \
  --default-language Chinese
```

---

## 7️⃣ 统一依赖管理

仓库统一使用根目录一个 `pyproject.toml`。

基础依赖：

```bash
uv sync
```

ASR 服务依赖：

```bash
uv sync --group asr_service
```

TTS 服务依赖：

```bash
uv sync --group tts_service
```

全部安装：

```bash
uv sync --group asr_service --group tts_service
```

---

## 8️⃣ 目录结构

```text
my-agent/
├─ src/                          # Agent 主逻辑
├─ qwen-livekit-stt/             # LiveKit 自定义 Qwen STT 插件
├─ qwen-asr-streaming-service/   # Qwen ASR 流式 WebSocket 服务
├─ qwen-tts-service/             # Qwen3-TTS HTTP 服务
├─ docs/                         # 部署文档
├─ pyproject.toml                # 唯一依赖配置文件
└─ README.md
```

---

## 9️⃣ 相关文档

- [`docs/LiveKit-Server部署.md`](./docs/LiveKit-Server部署.md)
- [`docs/LLM部署.md`](./docs/LLM部署.md)
- [`docs/系统架构与数据流.md`](./docs/系统架构与数据流.md)
- [`qwen-asr-streaming-service/README.md`](./qwen-asr-streaming-service/README.md)
- [`qwen-tts-service/README.md`](./qwen-tts-service/README.md)
