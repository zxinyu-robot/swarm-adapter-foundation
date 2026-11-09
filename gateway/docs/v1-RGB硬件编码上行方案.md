# v1 RGB 硬件编码上行方案（Orin NX NVENC → 5070 NVDEC）

> **版本**：v1.0-draft  
> **日期**：2026-08-06  
> **定位**：端侧 RGB 从中带宽上行通道的 **NVIDIA 硬件加速** 实现说明，作为 [`v1-双路上行语义调度方案.md`](./v1-双路上行语义调度方案.md) 中路 2 的推荐实现。  
> **前提**：RGB 已在 Linux SHM 环形缓冲；Super-LIO + BT 不得被编码线程阻塞。

---

## 1. 一句话

**SHM 零拷贝进 NVENC → H.265 码流上行 → 5070 NVDEC 解码进关键帧环缓冲 → VLM 按 1–4 Hz 取帧推理**；编码/解码均不走 CPU 软件路径。

---

## 2. 收益（客观预期）

| 指标 | 软件编码（x264/JPEG 15fps） | 硬件 H.265（NVENC） | 备注 |
|------|---------------------------|---------------------|------|
| CPU 占用 | 约 1–2 核 @ 640×480×15fps | **<5% 单核等效**（NVENC 专用引擎） | 具体值需 Orin NX 实测；数量级合理 |
| 端侧算力释放 | 与 Super-LIO / BT 争 CPU | 编码 offload 到 NVDEC/NVENC 引擎 | 主要收益点 |
| 上行带宽 | JPEG 1Hz ~200KB/s；15fps JPEG 更高 | H.265 15fps 通常 **1–3 Mbps** @ 720p 中等质量 | 低于原始 RGB ~165Mbps |
| 边侧解码延迟 | libjpeg / sw h264 数 ms~数十 ms | **NVDEC 单帧 <1 ms**（不含网络/缓冲） | 5070 有独立 NVDEC |
| 语义推理 | 不变 | 不变 | **15fps 不进 7B**；边侧仍 1–4 Hz 取关键帧 |

**注意**：上述 CPU/<5%、NVDEC <1ms 为 **工程目标区间**，写入验收项需真机 benchmark，不宜作为未测先验结论。

---

## 3. 数据通路

### 3.1 端侧 Orin NX（编码）

```text
相机 / V4L2 / ROS Image
        ↓
Linux SHM 环形缓冲 (15fps, NV12 或 RGBA)
        ↓  零拷贝 / EGLImage / NvBufSurface
GStreamer 或 Jetson Multimedia API
        ↓
nvv4l2h265enc (NVENC 硬件)
        ↓
H.265 Access Unit (Annex-B 或 AVCC)
        ↓
Tcp/Udp Sender → 边侧 :9878
```

**并行**：SubgraphPublisher 仍走 :9877 JSON，与码流 **独立通道、时间戳对齐**。

### 3.2 边侧 RTX 5070（解码 + 消费）

```text
H.265 码流接收
        ↓
NVDEC (nvv4l2decoder / FFmpeg h264_cuvid/hevc_cuvid)
        ↓
NV12/RGB 帧 → KeyframeRingBuffer (N≈60)
        ↓
Aligner: join(subgraph_version, pts, pose)
        ↓
FrameSelector: 1–4 帧/次 → Qwen-VL
```

---

## 4. Argus / EGL / GStreamer 选型说明

你提到的 **「Argus/EGL 把内存交给硬件编码器」** 在 Jetson 上需区分两种来源：

| RGB 来源 | 推荐管道 | Argus 是否必需 |
|----------|----------|----------------|
| **CSI 相机直采** | Argus → NvBuf → NVENC | ✅ 是 |
| **已有 SHM 环形缓冲**（Go2 自带相机经 ROS/V4L2 写入） | **appsrc/shmsrc → nvvidconv → nvv4l2h265enc** | ❌ 通常不用 Argus |

Go2 场景多为 **SHM 已有帧**，因此 v1 推荐：

- **EGL/NvBufSurface**：SHM → 注册为 NvBuffer → 零拷贝进 NVENC（避免 CPU 拷贝）
- **Argus**：仅当后续改为 Argus 直采相机时再引入

### 4.1 端侧 GStreamer 参考管道（SHM → H.265）

```bash
# 概念管道；shmsrc 参数按实际 socket/path 调整
gst-launch-1.0 -e \
  shmsrc socket-path=/tmp/rgb_shm is-live=true ! \
  video/x-raw,format=NV12,width=640,height=480,framerate=15/1 ! \
  nvvidconv ! \
  nvv4l2h265enc bitrate=2000000 iframeinterval=15 insert-sps-pps=true ! \
  h265parse ! \
  rtph265pay pt=96 ! \
  udpsink host=<5070_IP> port=9878
```

**参数建议（v1）**：

| 参数 | 值 | 说明 |
|------|-----|------|
| 分辨率 | 640×480 或 1280×720 | 与 SHM 一致 |
| 帧率 | 15 fps | 与采集一致 |
| 码率 | 2–4 Mbps | 室内导航可 2 Mbps 起 |
| GOP | 15（1 s） | 便于边侧 seek 最近 I 帧 |
| 格式 | NV12 进编码器 | Jetson NVENC 原生友好 |

### 4.2 边侧 GStreamer 解码参考

```bash
gst-launch-1.0 -e \
  udpsrc port=9878 ! \
  application/x-rtp,encoding-name=H265 ! \
  rtph265depay ! h265parse ! \
  nvv4l2decoder ! \
  nvvidconv ! video/x-raw,format=RGBA ! \
  appsink name=dec_sink
```

或使用 **FFmpeg** `hevc_cuvid` + `hwdownload` 写入 OpenCV/Qwen-VL 预处理。

---

## 5.  wire 格式：`motionslam.rgb_h265.v1`

v1 推荐 **RTP over UDP** 低延迟；联调初期可用 **TCP 长度前缀** 便于抓包。

### 5.1 TCP 帧封装（联调友好）

```text
H265K1 | u32 json_len | json_utf8 | u32 au_len | h265_access_unit_bytes
```

**JSON 侧车（每 GOP 或每 1 Hz 发一次，与子图 version 对齐）**：

```json
{
  "schema": "motionslam.rgb_h265.v1",
  "session_id": "local_session",
  "subgraph_version": 42,
  "keyframe_id": "kf_00017",
  "timestamp_ns": 1785316340000000000,
  "pose": { "x": 1.1, "y": -0.2, "yaw_rad": 0.10 },
  "width": 640,
  "height": 480,
  "fps": 15,
  "codec": "h265",
  "is_idr": true
}
```

### 5.2 与子图流对齐

- 子图 JSON（:9877）内 `keyframes_meta[].keyframe_id` 对应 H.265 侧车中的 `keyframe_id`
- 边侧 Aligner 规则：`subgraph_version` 一致 + `|timestamp_ns 差| < 500ms`
- **语义查询仍 1–4 Hz**：从 NVDEC 环缓冲 **按 PTS 抽取**，不对 15fps 全解码进 VLM

---

## 6. 线程与资源隔离（端侧）

```
┌─────────────────────────────────────────┐
│ CPU 亲和 / 优先级                         │
│  Super-LIO + BT     → 高优先级，绑大核    │
│  SubgraphPublisher  → 中优先级，独立线程  │
│  H.265 Encoder      → NVENC 硬件，低 CPU  │
│  SHM 写相机         → 不与编码同锁死      │
└─────────────────────────────────────────┘
```

**硬性要求**：

- 编码发送队列 **有界**（如 ≤30 帧）；网络阻塞时 **丢 P 帧保 I 帧**，不反压 Super-LIO
- 编码线程 **不得** 在 Super-LIO 实时回调里同步执行

---

## 7. 5070 边侧模块补充

| 模块 | 变更 |
|------|------|
| `RgbReceiver` | 收 H.265 AU / RTP → NVDEC 解码 |
| `KeyframeRingBuffer` | 存解码后 RGB + pts + pose 映射 |
| `FrameSelector` | 按 subgraph 节点选 1–4 帧；**与解码频率解耦** |
| `SemanticScheduler` | 输入不变；仍 Qwen-VL 1–4 张/查询 |

NVDEC 解码与 Qwen-VL 推理 **可同 GPU 分时**；v1 避免与 StreamVLN 7B 同 tick 并行。

---

## 8. 分阶段落地

| 阶段 | RGB 上行 | 目的 |
|------|----------|------|
| **P0 联调** | JPEG 1 Hz（RGBK1） | 协议/对齐/BT 先通 |
| **P0.5 生产** | H.265 15fps NVENC | 释放 NX CPU，边侧 NVDEC |
| **P1** | RTP + 侧车 JSON 精简 | 降延迟、减 TCP 头开销 |

**不建议** v1 第一天就上 H.265 阻塞语义联调；**建议** JPEG 通后立即切 NVENC 路径。

---

## 9. 验收 / Benchmark

| ID | 项 | 通过条件 |
|----|-----|----------|
| B1 | 端侧 CPU | NVENC 15fps 时 Super-LIO 帧耗时无明显退化（对比 JPEG 软编） |
| B2 | 编码占用 | `tegrastats` / `top` 编码相关 CPU **<10%**（目标 <5% 作 stretch） |
| B3 | 带宽 | 稳定 15fps，码流 **<5 Mbps** @ 720p |
| B4 | 边侧解码 | NVDEC 单帧 decode **<2 ms** p99（含缓冲则单独计网络） |
| B5 | 对齐 | subgraph_version 配对率 >95% |
| B6 | 断网 | 编码队列丢帧，Super-LIO/BT 不受影响 |

---

## 10. 风险

| 风险 | 缓解 |
|------|------|
| SHM 格式与 NvBuf 不兼容 | 统一 NV12；或 nvvidconv 一次转换 |
| Argus 误用到 SHM 路径 | SHM 走 appsrc，CSI 才走 Argus |
| H.265 延迟高于 JPEG 1Hz | 语义仍低频取帧；通信用 UDP/RTP |
| 5070 NVDEC 与推理争 GPU | 解码后帧 copy 到 CPU ring buffer，推理 batch 错开 |
| I 帧丢失导致长时间不可解码 | 周期 IDR（1 s）+ 侧车标记 `is_idr` |

---

## 11. 参考

- Jetson Linux Developer Guide — Multimedia API / GStreamer plugins (`nvv4l2h265enc`, `nvv4l2decoder`)
- NVIDIA Video Codec SDK — NVENC/NVDEC 能力表
- 总方案：[`v1-双路上行语义调度方案.md`](./v1-双路上行语义调度方案.md)
- 端侧任务：[`v1-端侧剩余工作清单.md`](./v1-端侧剩余工作清单.md) § T-P0-2
