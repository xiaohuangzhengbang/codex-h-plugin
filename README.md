# H Codex Plugin

H 是把 Kie 生成与 AdsPower TikTok 发布连在一起的 Codex 插件，所有电脑统一为三个顶层模式：

1. 批处理：递归扫描整个根目录，把所有 PID 图片一次性放进同一个并发池。
2. 单处理：只调用一次所选的 Kie 文本、图像、视频、放大或延长模型。
3. 发布：独立发布已有视频或计划表；批量和单次视频生成后也能直接发布本次结果。

## 从 GitHub 安装

GitHub 仓库是 H 的正式安装入口：

```text
https://github.com/xiaohuangzhengbang/codex-h-plugin.git
```

把上面的链接发给 Codex，并明确说“安装这个 H 插件”。Codex 必须把该仓库添加为插件 marketplace，然后安装其中的 `h`：

```bash
codex plugin marketplace add https://github.com/xiaohuangzhengbang/codex-h-plugin.git --ref main
codex plugin add h@codex-h-plugin
```

仓库中的 H 已标记为 `INSTALLED_BY_DEFAULT`。第二条命令仍作为幂等确认步骤，确保旧版 Codex 或已有 marketplace 状态下也完成安装。

如果 marketplace 已存在，先刷新再安装：

```bash
codex plugin marketplace upgrade codex-h-plugin
codex plugin add h@codex-h-plugin
```

安装完成后完全退出并重新打开 Codex，再新建任务调用 H。不要下载或解压 Release ZIP 作为正常安装方式。

## 首次环境准备

第一次调用 H 时只运行平台启动器：

- Windows：`scripts\h_run.cmd start`
- Intel Mac / Apple Silicon Mac：`./scripts/h_run.sh start`

启动器会按固定顺序完成环境识别：

1. 使用插件已有的内置运行时。
2. 使用之前缓存的 GitHub 运行时。
3. 使用 Codex 自带或系统已有的 Python 3.10+。
4. 若没有 Python，从本仓库 GitHub Release 自动下载与系统和芯片匹配的运行时。
5. 扫描 Node；缺少时从 Node.js 官方发布地址下载固定版本并校验内置 SHA-256。
6. Playwright 与 XLSX 依赖随 H 提供，不在目标电脑临时执行 `npm install`。
7. 所有运行时缓存到 `<home>/.codex/cache/h/`；GitHub 下载失败时才使用系统包管理器回退。

用户不需要自己安装 Python、Node、npm、pip、`requests` 或 Homebrew，也不需要处理 ZIP。运行时只下载一次，后续直接复用缓存。

## 固定交互

菜单由 `scripts/h_run.py` 的固定状态协议生成，技能只能逐字展示返回的 `display_text`，不能自行推荐、改写或遗漏选项。首屏始终是：

```text
哈喽小杨，你又开始工作啦，想不想小黄啊？

请选择处理模式，回复编号即可：
1. 批处理
2. 单处理
3. 发布
```

查看固定菜单：

```bash
./scripts/h_run.sh protocol mode
./scripts/h_run.sh protocol batch-image
./scripts/h_run.sh protocol single-video
```

Windows 把 `./scripts/h_run.sh` 替换为 `scripts\h_run.cmd`。

## Kie Key

Key 不会提交到 GitHub。配置以下任一来源即可：

```text
H_KIE_API_KEY
KIE_API_KEY
<home>/.codex/secrets/h_kie_api_key.txt
```

交互式设置：

```bash
./scripts/h_run.sh set-key
```

Windows 使用 `scripts\h_run.cmd set-key`。主动重新验证 Key、额度和网络时运行 `start --force-check`。

## 常用命令

查看模型目录：

```bash
./scripts/h_run.sh catalog
```

批量图片：

```bash
./scripts/h_run.sh process-images "/path/to/root" --workers 0 \
  --image-model 1 --image-resolution 1 --aspect-ratio 2 \
  --reverse-model 1 --image-reverse-meta-prompt "将每张产品图反推为详细 Kie 图片提示词。PID：{pid}"
```

批量视频：

```bash
./scripts/h_run.sh generate-videos "/path/to/root" --workers 0 \
  --video-model 3 --video-resolution 720p --aspect-ratio 2 \
  --reverse-model 1 --video-reverse-meta-prompt "将处理后的产品图反推为详细 Kie 视频提示词。PID：{pid}"
```

单次多图参考：

```bash
./scripts/h_run.sh single --kind image --model 1 --prompt "男装商品 Lookbook" \
  --media "/path/front.png" --media "/path/back.png" --media "/path/detail.png"
```

零张参考图自动走文生图；多张参考图共同进入同一个生成任务。批处理中的不同 PID 始终是独立任务，并在整个根目录范围并发。

## 生成后发布

视频生成成功后，H 的下一步菜单会直接显示“发布本次生成的视频”。H 使用生成结果 JSON 中的 `output_root`，自动收集成功视频，不再要求重新找路径：

```bash
./scripts/h_run.sh adspower plan --video-root "/path/to/H-result" \
  --profile-no 27 --start-at "2026-08-04 10:30" --interval-minutes 60 \
  --caption-template "{pid}" --hashtags "#TikTokShop" --attach-pid
./scripts/h_run.sh adspower check --profile-no 27
./scripts/h_run.sh adspower preview
```

Windows 把 `./scripts/h_run.sh` 替换为 `scripts\h_run.cmd`。预览会上传并填写表单，但不会点击最终发布。只有用户明确输入 `FABU` 后，H 才运行：

```bash
./scripts/h_run.sh adspower publish --publish-code FABU
```

独立发布可把普通视频目录交给 `adspower plan`，也可先用 `adspower validate --input-file <计划表>` 校验 XLSX/CSV，再预览。同一 AdsPower 环境内串行，不同环境并发；商品只使用完整数字 PID 精确匹配。

## 输出

批处理：`<home>/Desktop/H返回结果_<输入目录名>/`

单处理：`<home>/Desktop/H返回结果_单处理/`

内部固定创建：

```text
文本/
图像/
视频/
```

H 会立即保存已提交任务的 `task_id`。重跑时复用有效缓存、继续查询未完成任务，只重试失败项。图片和视频下载后均校验真实文件头，避免把参考图 URL 或 PNG 内容误存为 `.mp4`。

AdsPower 发布输出：`<home>/Desktop/H返回结果_发布/`，包含计划表、账号列表、逐次 JSON 报告、日志和失败截图。

## 安全

- TLS 证书验证始终开启。
- GitHub 运行时下载必须通过固定 SHA-256 校验。
- API Key 只允许保存在用户环境或用户 secrets 目录。
- 日志不输出完整 Key。
- AdsPower 默认先检查和预览；正式发布必须输入 `FABU`。
- 登录、验证码或风控只停止对应账号，最终发布按钮绝不自动重试。
- 曾经粘贴到公开仓库或公开记录中的 Key 应立即轮换。
