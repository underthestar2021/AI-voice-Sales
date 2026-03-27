# 🎙️ LiveKit Voice Agent

> 📌 项目目标：基于 `LiveKit Agents` 构建中文语音对话 Agent，支持在线链路运行，也支持本地自托管 ASR / TTS / LLM 组件联调。

---

## 1️⃣ 版本说明

### 🌐 Online 版本

- 入口：`src/agent_Online.py`
- 用途：线上可用链路、日常联调、优先启动
- 当前默认链路：
  - STT：火山引擎 `BigModelSTT`
  - LLM：DashScope 兼容接口上的 `qwen-flash`
  - TTS：MiniMax `speech-02-turbo`

启动命令：

```bash
uv run src/agent_Online.py dev
```

### 🧪 Local 版本

- 入口：`src/agent_Local.py`
- 用途：本地自托管组件验证，不是首选入口
- 当前默认链路：
  - STT：`QwenStreamingSTT + qwen-asr-streaming-service`
  - LLM：OpenAI 兼容接口接入自部署 `vLLM`
  - TTS：MiniMax `speech-02-turbo`

启动命令：

```bash
uv run src/agent_Local.py dev
```

### ✅ 推荐启动顺序

1. 优先启动 `Online` 版本
2. 仅在需要验证本地组件时再启动 `Local` 版本

---

## 2️⃣ 当前项目结构

- `src/agent_Online.py`
  在线版本 Agent 入口，优先使用。
- `src/agent_Local.py`
  本地版本 Agent 入口，用于自托管链路联调。
- `src/assistant.py`
  Agent 对话逻辑入口。
- `src/prompt.py`
  系统提示词。
- `src/rule_kb.py`
  规则库和知识块生成逻辑。
- `src/metrics_hooks.py`
  EOU、STT、LLM、TTS、网络探针等指标采集。
- `src/metrics_logger.py`
  JSONL 指标日志落盘工具。
- `qwen-asr-streaming-service/`
  自建 Qwen3-ASR 流式 WebSocket 服务。
- `qwen-livekit-stt/`
  LiveKit 自定义 STT 适配层。
- `qwen-tts-service/`
  自建 Qwen3-TTS HTTP 服务。

---

## 3️⃣ 快速开始

### 📦 安装主项目依赖

```bash
uv sync
```

### 🧾 复制环境变量模板

```bash
cp .env.example .env.local
```

### 🚀 优先启动 Online 版本

```bash
uv run src/agent_Online.py dev
```

### 🔧 如需验证本地链路，再启动 Local 版本

```bash
uv run src/agent_Local.py dev
```

---

## 4️⃣ 环境变量

主项目常用变量：

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `QWEN_STREAMING_STT_WS_URL`
- `QWEN_STREAMING_STT_MODEL`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`
- `MINIMAX_API_KEY`

说明：

- `Online` 版本主要依赖火山 STT、DashScope、MiniMax
- `Local` 版本主要依赖自建 Qwen ASR / vLLM

---

## 5️⃣ Qwen ASR 服务

### 🎧 作用

- 将 `Qwen3-ASR` 的 Python streaming inference 封装成 WebSocket 服务
- 接收 `16kHz / mono / PCM16` 音频流
- 返回 `interim` / `final` 转写结果

### 📁 目录

- `qwen-asr-streaming-service/`

### 📦 安装

```bash
cd qwen-asr-streaming-service
uv sync
```

### ▶️ 启动

```bash
uv run server.py \
  --model /root/my-vllm-py312-cu128/qwen/asr \
  --host 0.0.0.0 \
  --port 8001
```

### 🔌 默认地址

```text
ws://127.0.0.1:8001/ws
```

---

## 6️⃣ Qwen TTS 服务

### 🔊 作用

- 常驻加载 `Qwen3TTSModel`
- 通过 HTTP 提供最小可用接口
- 便于后续接入 LiveKit 自定义 TTS 插件

### 📁 目录

- `qwen-tts-service/`

### 📌 当前状态

- 已完成独立服务封装
- 当前还没有替换 `agent_Online.py` / `agent_Local.py` 中默认的 MiniMax TTS
- 现阶段属于自托管 TTS 服务模块

### 🌍 接口

- `GET /healthz`
- `GET /voices`
- `POST /tts`

### 📦 安装

```bash
cd qwen-tts-service
uv sync
```

### ▶️ 启动

```bash
uv run server.py \
  --model /root/my-vllm-py312-cu128/qwen/tts \
  --host 0.0.0.0 \
  --port 8091 \
  --device-map cuda:0 \
  --dtype bfloat16 \
  --default-speaker Vivian \
  --default-language Chinese
```

### 🧪 测试

健康检查：

```bash
curl http://127.0.0.1:8091/healthz
```

查看支持的 speaker / language：

```bash
curl http://127.0.0.1:8091/voices
```

生成音频：

```bash
curl -X POST http://127.0.0.1:8091/tts \
  -H "Content-Type: application/json" \
  -d '{
    "text": "其实我真的有发现，我是一个特别善于观察别人情绪的人。",
    "language": "Chinese",
    "speaker": "Vivian",
    "instruct": "自然、亲切、中文客服风格。"
  }' \
  --output output.wav
```

---

## 7️⃣ 日志

会话级指标默认写入：

```text
log/*.jsonl
```

常见事件：

- `transcript.interim`
- `transcript.final`
- `latency.stt_final`
- `latency.eou`
- `latency.llm`
- `latency.tts`
- `latency.e2e_user_to_first_audio`
- `latency.network_probe`

---

## 8️⃣ 相关文档

- [📘 LiveKit Server部署](docs/LiveKit-Server部署.md)
- [🧠 LLM部署](docs/LLM部署.md)
- [🧭 系统架构与数据流](docs/系统架构与数据流.md)
