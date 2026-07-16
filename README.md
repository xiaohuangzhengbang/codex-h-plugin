# H Codex Plugin

H 是只使用 Kie 的 Codex 插件，所有电脑统一为两个模式：

1. 批处理：递归扫描整个根目录，把所有 PID 图片一次性放进同一个并发池。
2. 单处理：只调用一次所选的 Kie 文本、图像、视频、放大或延长模型。

## 从 GitHub 安装

在 Codex 中把下面仓库添加为插件 marketplace，然后安装或启用 `h`：

```text
https://github.com/xiaohuangzhengbang/codex-h-plugin.git
```

仓库根目录已经包含 `.agents/plugins/marketplace.json` 和 `.codex-plugin/plugin.json`。安装后直接调用 H，不需要先运行安装命令。

## 首次自动准备

第一次调用 H 时，插件会自动完成：

1. 识别 Windows、Intel Mac 或 Apple Silicon Mac。
2. 优先寻找 Codex Desktop 自带 Python 3.10+。
3. 找不到时尝试系统 Python；Windows 最后使用 `winget` 自动安装用户级 Python 3.12，Mac 在已有 Homebrew 时自动安装 `python@3.12`。
4. 在 `<home>/.codex/cache/h` 创建独立可复用环境。
5. 扫描 `requirements.txt` 和实际 import，自动安装或修复缺失依赖。
6. 检查桌面写入权限；有 Kie Key 时验证一次接口并缓存 ready 状态。

插件更新或依赖变化时会自动建立新环境。平时启动只做快速检查，不会每次重装或长时间验证。

Windows 手动检查入口：

```powershell
scripts\h_run.cmd start
```

macOS 手动检查入口：

```bash
./scripts/h_run.sh start
```

## 固定交互

菜单由 `scripts/h_run.py` 的固定状态协议生成，技能只能逐字展示返回的 `display_text`，不能自行推荐、改写或遗漏选项。首屏始终是：

```text
哈喽小杨，你又开始工作啦，想不想小黄啊？

请选择处理模式，回复编号即可：
1. 批处理
2. 单处理
```

查看任一固定菜单：

```bash
./scripts/h_run.sh protocol mode
./scripts/h_run.sh protocol batch-image
./scripts/h_run.sh protocol single-video
```

Windows 把 `./scripts/h_run.sh` 替换为 `scripts\h_run.cmd`。

## Kie Key

Key 不会提交到 Git。配置以下任一来源即可：

```text
H_KIE_API_KEY
KIE_API_KEY
<home>/.codex/secrets/h_kie_api_key.txt
```

交互式本地设置：

```bash
./scripts/h_run.sh set-key
```

Windows 使用 `scripts\h_run.cmd set-key`。主动重新验证 Key、额度和网络时运行 `start --force-check`。

## 常用命令

查看实时模型目录：

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

零张参考图自动走文生图；一张或多张共同进入同一个参考图任务。批处理中的不同 PID 始终是独立任务，并在整个根目录范围并发。

## 输出

批处理：`<home>/Desktop/H返回结果_<输入目录名>/`

单处理：`<home>/Desktop/H返回结果_单处理/`

两者内部固定创建：

```text
文本/
图像/
视频/
```

H 会立即保存每个已提交任务的 `task_id`。重跑时复用有效缓存、继续查询未完成任务，只重试失败项，避免重复扣费。图片和视频下载后都会校验真实文件头，防止把 PNG 或上传参考地址误存成 `.mp4`。

## 安全

- TLS 证书校验始终开启。
- API Key 只允许保存在用户环境或用户 secrets 目录。
- 日志不输出完整 Key。
- 曾经粘贴到公开仓库或公开记录中的 Key 应立即轮换。
