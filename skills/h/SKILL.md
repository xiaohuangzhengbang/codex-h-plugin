---
name: h
description: "Kie-only fixed workflow for whole-folder concurrent batch processing and one-model single processing. Use for PID product folders, Kie reverse prompting, text or image generation, image or text to video, Grok transforms, and saved-task resume."
---

# H 固定控制器

H 只调用 Kie。用户界面只有两个顶层模式：批处理、单处理。

## 不可变规则

1. 不得凭语言模型自行编写、改写、翻译、删减或重新排序菜单。
2. 每个新任务第一次响应用户之前，必须先运行 H 启动器的 `start` 命令。
3. 读取命令输出中的最后一个 JSON，只逐字显示 `display_text`。不得把启动日志、JSON 或额外说明发给用户。
4. 后续需要菜单时，必须运行 `protocol <state>`，继续逐字显示返回的 `display_text`。
5. 不得直接运行 `kie_video_batch.py`，不得手动寻找或安装 Python、pip 或 `requests`。便携包必须使用内置运行程序；源码版启动器只作为开发回退。
6. `start` 返回 `key-required` 或 `setup-error` 时，只显示 `display_text`，不得提交任何 Kie 生成任务。

从本 `SKILL.md` 定位插件根目录，再从根目录运行对应启动器：

- Windows：`scripts\h_run.cmd`
- Intel Mac / Apple Silicon Mac：`./scripts/h_run.sh`

新任务固定先运行：

```text
<launcher> start
```

正式便携包中的启动器必须优先运行插件 `runtime/` 内的 `h_launcher` 和 `h_core`，它们已包含运行环境，不得下载 Python。只有源码开发版不存在内置程序时，启动器才允许扫描 Codex/系统 Python，并在 `<home>/.codex/cache/h` 创建隔离环境。

## 固定状态

只允许下列状态；显示前必须调用 `<launcher> protocol <state>`：

| 状态 | 用途 |
| --- | --- |
| `mode` | 选择批处理或单处理 |
| `batch-root` | 取得批处理根目录 |
| `batch-image` | 一次取得图片模型、1/2/4K、比例、反推模型和元提示词 |
| `batch-video` | 一次取得视频模型、时长、分辨率、比例、反推模型和元提示词 |
| `single-kind` | 选择文本、图像或视频 |
| `single-text` | 文本模型和 prompt |
| `single-image` | 图像模型、1/2/4K、比例、prompt 和零张或多张参考图 |
| `single-video` | 视频模型、最大时长和模型所需媒体 |
| `post-images` | 批量图片完成后的下一步 |
| `post-videos` | 批量视频完成后的下一步 |
| `post-single` | 单处理完成后的下一步 |

若用户在首次消息中已经明确模式或给齐参数，仍先静默执行 `start`。环境 ready 后可直接进入对应状态，不重复询问已有信息。

固定流转：

- `mode` 选 1 -> `batch-root`；选 2 -> `single-kind`。
- 取得批处理根目录 -> `batch-image` -> 执行图片批处理 -> `post-images`。
- `post-images` 选继续视频 -> `batch-video` -> 执行视频批处理 -> `post-videos`。
- `single-kind` 选文本/图像/视频 -> `single-text` / `single-image` / `single-video` -> 执行 -> `post-single`。
- “重试”使用原命令或 `resume`，不得创建新的重复任务；“新的处理”回到对应固定状态。

## 密钥与验证

密钥读取顺序：`--api-key`、`H_KIE_API_KEY`、`KIE_API_KEY`、`<home>/.codex/secrets/h_kie_api_key.txt`、插件本地 `.h_api_key`。不得把密钥写入仓库、回复或日志。

第一次本地环境准备完成且检测到密钥时，`start` 会验证一次 Kie；验证成功后缓存当前插件版本的 ready 状态，避免每次打开都等待。需要主动复验时运行：

```text
<launcher> start --force-check
```

失败必须使用返回归因：`authentication` 密钥、`quota` 额度、`validation` 参数、`rate_limit` 限流、`maintenance/provider` 服务端、`network` 网络/TLS、`runtime` 本地环境。验证失败时不得盲目重试生成。

## 批处理

批处理递归扫描用户给出的整个根目录。所有合格 PID 图片必须一次性进入同一个并发池；子文件夹只用于保持输出层级，绝不能逐文件夹提交后等待。`--workers 0` 表示按整棵目录的任务数并发，最多 64。

图片命令：

```text
<launcher> process-images <根目录> --workers 0 --image-model <编号> --image-resolution <编号> --aspect-ratio <编号> --reverse-model <编号> --image-reverse-meta-prompt <提示词>
```

默认中文图片反推元提示词：

```text
将每张产品图片反推为详细、可直接用于 Kie 的图片生成提示词，严格保留服装版型、颜色、面料和细节。PID：{pid}
```

每个 PID 都要把自己的原图上传给 Kie 文本模型反推，再把同一原图和反推结果交给图片模型。不得跨 PID 复用反推文本。不得把不同 PID 合并成一个多图参考任务。

视频命令：

```text
<launcher> generate-videos <同一根目录> --workers 0 --video-model <编号> --duration <秒> --video-resolution <分辨率> --aspect-ratio <编号> --reverse-model <编号> --video-reverse-meta-prompt <提示词>
```

命令结束后读取末尾 JSON，固定报告输出目录、成功数、失败数、失败 PID 和 `error_category`，然后立即显示对应 `post-*` 菜单。退出码 `2` 仅表示部分项目失败，不是整批崩溃。

## 单处理

单处理只提交一个用户所选模型任务：

```text
<launcher> single --kind <text|image|video> --model <编号> --prompt <提示词> [模型参数]
```

- 图像不上传图片即文生图；上传一张或多张即多图参考生成。每张图片按用户顺序重复传入一个 `--media`，不得只取第一张。
- 多张参考图共同生成一个结果；每张图各自生成一个结果应切换批处理。
- 视频图片重复用 `--media`，视频参考重复用 `--video-ref`，音频参考重复用 `--audio-ref`；Gemini Omni 使用 `--audio-id` / `--character-id`。
- Grok Upscale/Extend 只接受以前的 Kie Grok `--source-task-id`，不得把外部视频冒充任务 ID。
- 输入数量、比例、分辨率和时长始终以 `single-*` 固定菜单内的实时目录为准，超限必须在提交前报错。

继续已提交任务：

```text
<launcher> resume <JSON任务记录路径>
```

## 输出与续跑

批处理默认输出到 `<home>/Desktop/H返回结果_<根目录名>/`，单处理默认输出到 `<home>/Desktop/H返回结果_单处理/`；内部固定有 `文本/`、`图像/`、`视频/` 三个目录。

提交成功后立即保存 `task_id`、请求签名和预期文件。网络中断或超时保留可续跑状态。只有请求签名匹配且文件头有效才命中缓存；图片必须是真实图片文件头，视频必须是真实 MP4/WebM 文件头。更改原图、模型、prompt、比例或分辨率必须重新生成。

生成结束绝不能直接结束对话，必须显示相应 `post-images`、`post-videos` 或 `post-single` 菜单。
