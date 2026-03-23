# 🎙️ LiveKit-Voice-Agent

一个基于 **LiveKit Agents** 的中文语音助手项目，面向电话语音场景，支持实时 STT、LLM 推理和 TTS 播报，并内置完整延迟指标日志。

## 🚀 当前技术栈

- 🗣️ STT：火山引擎 `BigModelSTT`
- 🧠 LLM：OpenAI 兼容接口（默认 DashScope `qwen-flash`）
- 🔊 TTS：MiniMax `speech-02-turbo`
- 📊 指标日志：JSONL（会话级事件与时延）

## 📁 项目结构

- `src/agent.py`：主入口，负责会话装配、连接房间、启动服务
- `src/assistant.py`：对话智能体逻辑（提示词 + 规则命中 + LLM 注入）
- `src/prompt.py`：系统提示词（保险销售场景）
- `src/rule_kb.py`：正则规则库与知识注入
- `src/metrics_hooks.py`：会话事件与时延指标采集（EOU/STT/LLM/TTS/网络探针）
- `src/metrics_logger.py`：指标落盘工具（JSONL writer）

## 📚 文档导航

- 🏠 LiveKit Server 部署：[docs/LiveKit-Server部署.md](docs/LiveKit-Server部署.md)
- 🧠 LLM 服务部署：[docs/LLM部署.md](docs/LLM部署.md)
- 🔁 系统架构与数据流：[docs/系统架构与数据流.md](docs/系统架构与数据流.md)

## ⚙️ 快速开始

1. 复制环境变量模板并填写：

```bash
cp .env.example .env.local
```

2. 安装依赖：

```bash
uv sync
```

3. 启动 Agent：

```bash
uv run src/agent.py dev
```

## 🧾 日志说明

日志默认写入：

`../log/*.jsonl`

常见事件包括：

- `transcript.interim`：中间转写（更快展示）
- `transcript.final`：最终转写（用于回填确认）
- `latency.stt_final`：用户停说到 final 转写完成的耗时
- `latency.eou`：端点检测相关耗时
- `latency.llm`：LLM 首 token 与总推理耗时
- `latency.tts`：TTS 首包与总合成耗时
- `latency.e2e_user_to_first_audio`：用户到 AI 首音频端到端耗时
- `latency.network_probe`：LiveKit 目标地址 TCP RTT 探针

## 🧠 运行机制

- 使用 `turn_detection="stt"`，由 STT 侧判定说话结束
- 展示策略为 “interim 优先 + final 回填”
- 指标采集与业务逻辑已解耦，便于后续扩展与维护

## 🔐 环境变量（示例）

请参考 `.env.example` 与 `.env.local`，重点包含：

- `LIVEKIT_URL`
- `LIVEKIT_API_KEY`
- `LIVEKIT_API_SECRET`
- `VOLCENGINE_STT_APP_ID`
- `VOLCENGINE_STT_ACCESS_TOKEN`
- `DASHSCOPE_API_KEY`
- `MINIMAX_API_KEY`
