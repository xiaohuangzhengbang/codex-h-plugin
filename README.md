# H Codex Plugin

H 是只使用 Kie 的 Codex 插件，所有电脑统一为两个顶层模式：

1. 批处理：递归扫描整个根目录，把所有 PID 图片一次性放进同一个并发池。
2. 单处理：只调用一次所选的 Kie 文本、图像、视频、放大或延长模型。

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
5. 对下载文件执行固定 SHA-256 校验，然后缓存到 `<home>/.codex/cache/h/github-runtime`。
6. GitHub 下载失败时，才尝试 Homebrew 或 winget 作为最后回退。

用户不需要自己安装 Python、pip、`requests` 或 Homebrew，也不需要处理 ZIP。运行时只下载一次，后续直接复用缓存。

## 固定交互

菜单由 `scripts/h_run.py` 的固定状态协议生成，技能只能逐字展示返回的 `display_text`，不能自行推荐、改写或遗漏选项。首屏始终是：

```text
哈喽小杨，你又开始工作啦，想不想小黄啊？

请选择处理模式，回复编号即可：
1. 批处理
2. 单处理
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

## 安全

- TLS 证书验证始终开启。
- GitHub 运行时下载必须通过固定 SHA-256 校验。
- API Key 只允许保存在用户环境或用户 secrets 目录。
- 日志不输出完整 Key。
- 曾经粘贴到公开仓库或公开记录中的 Key 应立即轮换。
