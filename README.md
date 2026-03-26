# LiveKit-Voice-Agent

基于 `LiveKit Agents` 的中文语音销售 Agent 项目，面向实时语音对话场景，包含 STT、LLM、TTS 和延迟日志采集能力。

## 当前链路

- STT：当前本地入口默认使用火山引擎 `BigModelSTT`
- LLM：通过 OpenAI 兼容接口接入自部署 vLLM
- TTS：MiniMax `speech-02-turbo`
- 日志：会话级 JSONL 指标日志

## 项目结构

- `src/agent_Local.py`
  本地运行入口。负责组装 AgentSession、连接 LiveKit、注册日志钩子。
- `src/agent_Online.py`
  线上模型版本入口。
- `src/assistant.py`
  Agent 对话逻辑入口，包含提示词和规则命中注入。
- `src/prompt.py`
  系统提示词。
- `src/rule_kb.py`
  正则规则库和命中后的知识块生成逻辑。
- `src/metrics_hooks.py`
  EOU、STT、LLM、TTS、网络探针等指标采集。
- `src/metrics_logger.py`
  JSONL 日志落盘工具。
- `qwen-asr-streaming-service/`
  独立的 Qwen3-ASR 流式服务。
- `qwen-livekit-stt/`
  LiveKit 自定义 STT 适配层，用于接入上面的 Qwen ASR 服务。

## 文档

- [LiveKit Server部署](docs/LiveKit-Server部署.md)
- [LLM部署](docs/LLM部署.md)
- [系统架构与数据流](docs/系统架构与数据流.md)

## 快速开始

1. 复制环境变量模板：

```bash
cp .env.example .env.local
```

2. 安装依赖：

```bash
uv sync
```

3. 启动本地 Agent：

```bash
uv run src/agent_Local.py dev
```

## 环境变量

重点变量包括：

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `VOLCENGINE_STT_APP_ID`
- `VOLCENGINE_STT_ACCESS_TOKEN`
- `MINIMAX_API_KEY`
- `LLM_BASE_URL`
- `LLM_API_KEY`
- `LLM_MODEL`

## 日志说明

日志默认写入：

```text
log/*.jsonl
```

常见事件包括：

- `transcript.interim`
  中间转写结果
- `transcript.final`
  最终转写结果
- `latency.stt_final`
  用户停说到最终转写完成的耗时
- `latency.eou`
  端点检测相关耗时
- `latency.llm`
  LLM 首 token 和总推理耗时
- `latency.tts`
  TTS 首包和总合成耗时
- `latency.e2e_user_to_first_audio`
  用户到 AI 首音频的端到端耗时
- `latency.network_probe`
  到 LiveKit 目标地址的 TCP RTT

## Qwen ASR 模块

### `qwen-asr-streaming-service`

作用：

- 将 Qwen3-ASR 的 Python streaming inference 封装成独立 WebSocket 服务
- 接收 `16kHz / mono / PCM16` 音频流
- 返回 `interim` 和 `final` 转写结果

典型用法：

```bash
cd qwen-asr-streaming-service
uv sync
uv run server.py --model ./qwen/asr --host 0.0.0.0 --port 8001
```

服务地址示例：

```text
ws://127.0.0.1:8001/ws
```

### `qwen-livekit-stt`

作用：

- 作为 LiveKit 侧的自定义 STT 插件
- 将 LiveKit 音频帧转发到 `qwen-asr-streaming-service`
- 将返回的 `interim/final` 转换成 LiveKit `SpeechEvent`

典型用法：

- 在 `src/agent_Local.py` 中引入 `QwenStreamingSTT`
- 通过 `QWEN_STREAMING_STT_WS_URL` 指向 ASR 服务地址

示例：

```env
QWEN_STREAMING_STT_WS_URL=ws://<asr-host>:8001/ws
```

如果 Agent 和 ASR 服务在同一台机器，建议优先使用：

```env
QWEN_STREAMING_STT_WS_URL=ws://127.0.0.1:8001/ws
```

## 说明

当前仓库里已经包含这两个模块的源码，是作为普通目录并入仓库，不是 Git submodule。
