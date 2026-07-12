---
name: h
description: "Kie-only text, image, and video workflow with two user-facing modes: whole-folder concurrent batch processing and one-model single processing. Use for PID product folders, Kie reverse prompting, image generation, video generation, Grok post-processing, or resuming saved Kie tasks."
---

# H

H 只调用 Kie。首次回复必须先说：

```text
哈喽小杨，你又开始工作啦，想不想小黄啊？
```

## 固定入口

用户尚未说明模式时，只问：

```text
请选择处理模式，回复编号即可：
1. 批处理
2. 单处理
```

- 批处理：递归扫描整个根目录，所有 PID 图片进入同一个并发池；文件夹只负责保持输出层级，不能逐文件夹串行等待。
- 单处理：只调用一次用户选择的模型，不把媒体目录拆成 PID 批次。
- 用户已明确说“全部、整个文件夹、批量”或“单次、一个模型”时直接进入对应模式，不重复问。

## 启动与密钥

始终通过便携启动器运行，不能直接运行 `kie_video_batch.py`：

- Windows：`scripts\h_run.cmd`
- macOS Intel / Apple Silicon：`./scripts/h_run.sh`

首次使用先运行 `doctor`。启动器在 `<home>/.codex/cache/h` 一次性创建并复用 Python 虚拟环境；不要手工安装 `requests`，也不要在插件目录创建新环境。

密钥顺序：`--api-key`、`H_KIE_API_KEY`、`KIE_API_KEY`、`<home>/.codex/secrets/h_kie_api_key.txt`、插件本地 `.h_api_key`。缺少密钥时只说明需要进行一次密钥设置；不得把密钥写进仓库、回复或日志。

```text
scripts/h_run.sh doctor
scripts\h_run.cmd doctor
```

若 `doctor` 失败，按返回类别直接归因：`authentication` 密钥、`quota` 额度、`validation` 参数、`rate_limit` 限流、`maintenance/provider` 服务端、`network` 网络/TLS。不要盲目重复提交生成任务。

## 模型目录

每次选择前运行 `catalog`，把对应类别的全部编号列给用户。不能只给推荐项，也不能把同一模型的文生/图生端点拆成两个用户选项。

```text
scripts/h_run.sh catalog
scripts\h_run.cmd catalog
```

- 文本：GPT 5.5 Response、GPT 5.4 Response、Gemini 3.1 Pro、Gemini 3 Pro、Gemini 3.5 Flash、Gemini 3 Flash。
- 图像：GPT Image-2、Nano Banana、Nano Banana Pro、Nano Banana 2、Nano Banana 2 Lite、Seedream 5.0 Lite。列模型时必须同时显示每次生成可上传的参考图上限。
- 视频：Grok Imagine、Grok Imagine Video 1.5 Preview、Veo3.1 Lite/Fast/Quality、Gemini Omni Video、Seedance 2.0/Fast/Mini；单处理另可选 Grok Upscale/Extend。

GPT 5.5 暂时不可用时脚本自动回退 GPT 5.4；鉴权、额度或参数错误不得回退。JSON 记录必须显示请求模型、实际模型和是否回退。

## 批处理

先取得根目录，再一次询问图片生成所需参数：

```text
请选择图片参数，按顺序回复：图片模型 分辨率 比例

图片模型：
1. GPT Image-2（0 图文生图；1-16 图多图参考）
2. Nano Banana（0 图文生图；1-10 图多图参考）
3. Nano Banana Pro（0 图文生图；1-8 图多图参考）
4. Nano Banana 2（0 图文生图；1-14 图多图参考）
5. Nano Banana 2 Lite（0 图文生图；1-10 图多图参考）
6. Seedream 5.0 Lite（0 图文生图；1-14 图多图参考）

分辨率：
1. 1K
2. 2K
3. 4K

比例：
1. 9:16
2. 16:9
```

随后列出全部反推文本模型并收集反推元提示词。默认元提示词仅在用户直接回车时使用：

```text
将每张产品图片反推为详细、可直接用于 Kie 的图片生成提示词，严格保留服装版型、颜色、面料和细节。PID：{pid}
```

运行：

```text
scripts/h_run.sh process-images <根目录> --image-model <编号> --image-resolution <编号> --aspect-ratio <编号> --reverse-model <编号> --image-reverse-meta-prompt <提示词>
```

`--workers 0` 表示整棵目录按项目数并发，最多 64；不要改成逐项等待。每个 PID 使用自己的原图进行 Kie 多模态反推，再用同一原图生成，不能跨 PID 复用提示词。

批处理中的多张源图是多个独立商品任务，必须整批并发；不能把不同 PID 合并成同一次多图参考生成。要让多张参考图共同生成一个结果，应使用单处理。

图片完成后，必须显示输出根目录、成功数、失败数和失败 PID/类别，然后显示：

```text
请选择下一步：
1. 继续生成视频
2. 只重试失败项
3. 处理新的文件夹
4. 结束
```

选择 2 时原命令重跑即可：脚本校验成功缓存，只重做失败项，并继续已保存的 `task_id`，不能重复提交仍在运行的任务。

选择 1 后，一次收集视频模型、时长、分辨率、比例、反推文本模型和视频反推元提示词。必须显示模型最长时长：Grok 30 秒，Grok 1.5 Preview 15 秒，Veo 固定约 8 秒，Seedance 15 秒；Gemini Omni 显示“按 Kie 当前支持”，不得猜测上限。

```text
scripts/h_run.sh generate-videos <同一根目录> --video-model <编号> --duration <秒> --video-resolution <分辨率> --aspect-ratio <编号> --reverse-model <编号> --video-reverse-meta-prompt <提示词>
```

视频完成后必须显示：

```text
请选择下一步：
1. 只重试失败项
2. 处理新的文件夹
3. 结束
```

## 单处理

运行 `catalog` 后让用户选择文本、图像或视频模型，并在同一轮收齐该模型需要的 prompt、媒体、比例、分辨率、时长。图像和视频模型根据媒体自动路由：0 图走文生，上传图走图生。

单处理选择图像模型时，必须把该模型的参考图上限与比例、分辨率一起列出，并明确允许用户一次附上多张图片。收到多张图片后要全部保留，按原顺序为每张图片重复传入一个 `--media`，不能只取第一张。多张参考图共同进入一个 Kie 生成任务；若用户希望每张图各自生成一个结果，应切换批处理。

```text
scripts/h_run.sh single --kind <text|image|video> --model <编号> --prompt <提示词> [模型参数]
```

媒体参数：图片重复使用 `--media`，视频参考重复使用 `--video-ref`，音频参考重复使用 `--audio-ref`；Gemini Omni 使用 `--audio-id` / `--character-id`。Grok Upscale/Extend 只接受之前的 Kie Grok `--source-task-id`，不能上传外部视频冒充任务。

单处理结束后必须显示返回文件和：

```text
请选择下一步：
1. 重试或继续当前任务（已提交任务只查询，不重复提交）
2. 继续新的单处理
3. 切换到批处理
4. 结束
```

继续已提交任务：

```text
scripts/h_run.sh resume <JSON任务记录路径>
```

## 输入规则

- 图片模型：GPT Image-2 最多 16 图；Nano Banana 最多 10 图；Nano Banana Pro 最多 8 图；Nano Banana 2 最多 14 图；Nano Banana 2 Lite 最多 10 图；Seedream 5.0 Lite 最多 14 图。0 图自动文生图，1 图或多图自动走该模型的参考图生成；超过对应上限在提交前直接报错。
- Veo：0 图文生；1-2 图首尾帧；3 图仅 Lite/Fast 参考图；超过 3 图报错；不允许视频/音频。
- Grok：0 图文生；1 图图生；超过 1 图报错；不允许视频/音频。
- Seedance：0 图文生；1 图首帧；2 图首尾帧；3-9 图或含视频/音频时走多模态参考。
- Gemini Omni：`图片数 + 2 * 视频数 + 角色ID数 <= 7`，视频最多 1 个，角色 ID 最多 3 个；音频必须是 Kie audio ID。
- 图片下载必须通过真实图片文件头校验；视频必须通过 MP4/WebM 文件头校验。HTML、原始上传 URL 或伪扩展名都算失败。

## 输出与状态

默认输出：

```text
<home>/Desktop/H返回结果_<根目录名>/
  文本/
  图像/
  视频/

<home>/Desktop/H返回结果_单处理/
  文本/
  图像/
  视频/
```

提交成功后立即保存 `task_id`、请求签名和预期输出路径。网络中断或超时保留为可续跑状态。只有签名匹配且文件头有效的结果才能命中缓存；更换原图、模型、提示词、比例或分辨率必须重新生成。

命令退出码 `2` 表示批次部分失败，不是整批崩溃。读取末尾 JSON 汇总后向用户报告结果并继续显示下一步，绝不能生成完一次就直接结束对话。
