# Qwen3-ASR 流式服务

这是一个独立于 `my-agent` 的最小流式 STT 服务模块，用来把 `Qwen3-ASR` 官方提供的 Python streaming inference 能力封成一个 WebSocket 服务，方便后续接入 LiveKit。

## 作用

- 不再使用 `vllm serve ... /v1/audio/transcriptions` 的整段转写模式
- 直接在服务进程里初始化 `Qwen3ASRModel.LLM(...)`
- 每个 WebSocket 连接维护一份 streaming state
- 持续接收 PCM 音频块并返回 `interim` / `final`

## 目录

- `server.py`
  流式服务入口
- `pyproject.toml`
  这个独立模块的依赖定义

## 依赖安装

建议在服务器上进入这个目录后用 `uv` 安装：

```bash
cd /root/LiveKit/qwen-asr-streaming-service
uv sync
```

如果你已经在目标虚拟环境里，也可以：

```bash
uv add "qwen-asr[vllm]" fastapi uvicorn numpy
```

## 启动

```bash
uv run server.py \
  --model ./qwen/asr \
  --host 0.0.0.0 \
  --port 8001 \
  --gpu-memory-utilization 0.8 \
  --max-new-tokens 32
```

说明：

- 启动这个服务时，不需要再额外启动 `vllm serve`
- 这个进程内部会直接创建 `Qwen3ASRModel.LLM(...)`
- 默认 WebSocket 地址为 `ws://<host>:8001/ws`

## 协议

### 客户端发送

先发一条文本控制消息：

```json
{"type":"start"}
```

然后持续发送二进制音频块：

- 格式：`PCM16 little-endian`
- 声道：单声道
- 采样率：`16000`

结束时发送：

```json
{"type":"finish"}
```

### 服务端返回

开始成功：

```json
{"type":"started"}
```

中间增量结果：

```json
{"type":"interim","text":"你好","language":"zh"}
```

最终结果：

```json
{"type":"final","text":"你好。","language":"zh"}
```

错误：

```json
{"type":"error","message":"..."}
```

## 健康检查

```bash
curl http://127.0.0.1:8001/healthz
```

预期返回：

```json
{"status":"ok"}
```

## 接入 LiveKit 的建议

后续在 LiveKit 里不要继续使用 `openai.STT(...)` 去接 `Qwen3-ASR`。

建议写一个自定义 STT 插件，逻辑如下：

1. 建立到 `ws://<asr-host>:8001/ws` 的连接
2. 发送 `{"type":"start"}`
3. 把 LiveKit 音频帧转换成 `16k PCM16`
4. 持续发送二进制音频块
5. 收到 `interim/final` 后转换成 LiveKit `SpeechEvent`

## 当前限制

- 当前版本只实现单会话单状态的最小能力
- 默认假设输入音频已经是 `16kHz/mono/PCM16`
- 还没有加鉴权、限流、日志落盘和连接复用
- 还没有做多 worker / GPU 资源隔离

这版的目标不是直接生产可用，而是尽快验证 `Qwen3-ASR` 流式链路和 LiveKit 的接入方式。

