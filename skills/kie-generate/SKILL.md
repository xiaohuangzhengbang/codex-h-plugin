---
name: kie-generate
description: 通过 H 使用 Kie 文本、图像和视频模型进行单次或整文件夹并发生成。用于用户上传图片、给出图片文件夹、要求图生视频、文生图、多图参考、AI 分析图片与标题、批量 PID 视频生成或继续已提交任务。
---

# H 生成

只运行 H 平台启动器，不直接运行内部 Python：

- Windows：`scripts\h_run.cmd`
- Intel Mac / Apple Silicon Mac：`./scripts/h_run.sh`

1. 静默运行 `<launcher> start --capability generate`。
2. 若输入是文件夹，显示 `protocol batch-image` 或 `protocol batch-video`，整棵目录使用 `--workers 0` 一次并发，不得按子文件夹等待。
3. 若输入是一张或多张图片，显示 `protocol single-image` 或 `protocol single-video`；每张参考图按顺序重复 `--media`。
4. 用户已经给齐模型、分辨率、比例、时长和提示词时直接执行，不重复询问。
5. 图片同目录存在 `fastmoss-product.json` 时，H 自动把 FastMoss 标题与图片一起交给文本模型分析。
6. 保存 task ID；继续任务只查询已有 ID，不重复提交。
7. 视频成功后必须显示 `post-videos` 或 `post-single-video`，第一项为发布本次结果。

识别到用户上传图片时始终使用该图片。若同时提供 PID，PID 只用于补充 FastMoss 标题、商品数据和后续精确挂车。
