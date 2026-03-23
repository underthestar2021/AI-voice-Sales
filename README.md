# my-agent

基于 LiveKit Agents 的中文语音 Agent，当前固定链路为：

- STT: 火山引擎 `BigModelSTT`
- LLM: OpenAI 兼容接口（默认 DashScope `qwen-flash`）
- TTS: Minimax `speech-02-turbo`

## 项目结构

`src/agent.py`  
主入口，组装 STT/LLM/TTS、连接 LiveKit 房间、采集延迟日志。

`src/assistant.py`  
对话智能体，注入系统提示词，按用户问题命中规则知识。

`src/prompt.py`  
保险销售场景系统提示词。

`src/rule_kb.py`  
正则规则库与知识注入逻辑。

`src/metrics_logger.py`  
JSONL 指标落盘工具。

`docs/livekit_demo_sequence.md`  
链路时序和架构说明。

## 运行

1. 复制并填写环境变量：
```bash
cp .env.example .env.local
```

2. 安装依赖：
```bash
uv sync
```

3. 启动 agent：
```bash
uv run src/agent.py dev
```

## 日志

延迟日志写入仓库外层目录：

`D:\Worker\LiveKit\log\*.jsonl`

常见事件：

- `latency.eou`
- `latency.stt`
- `latency.stt_final`
- `latency.llm`
- `latency.tts`
- `latency.e2e_user_to_first_audio`
- `transcript.interim`
- `transcript.final`

## 说明

- 当前使用 `turn_detection="stt"`，由 STT 侧判停。
- 本仓库已移除历史 FunASR/MeloTTS 代码，仅保留当前在线链路实现。
