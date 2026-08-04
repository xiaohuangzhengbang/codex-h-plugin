---
name: adspower-publish
description: 通过 H 与 AdsPower Local API 扫描账号，把 H 生成结果、普通视频目录或 XLSX/CSV 计划表安全预览、排期并发布到 TikTok。用于 AdsPower 发布、TikTok 批量发布、生成后发布、账号检查、定时发布、商品 PID 挂车或失败排查。
---

# H AdsPower 发布

本技能属于 H。只运行 H 的平台启动器，不直接运行 PowerShell、Node、Playwright 或内部脚本：

- Windows：`scripts\h_run.cmd`
- Intel Mac / Apple Silicon Mac：`./scripts/h_run.sh`

## 固定流程

1. 新任务先运行 `<launcher> start --capability publish`，逐字显示末尾 JSON 的 `display_text`。只有发布入口会准备 AdsPower/Node，不能在 PID 或生成入口提前加载。
2. 运行 `<launcher> adspower init` 创建默认工作目录、配置和计划模板。
3. 运行 `<launcher> adspower profiles` 获取环境编号。
4. 运行 `<launcher> adspower check`，真实进入 TikTok Studio 检查登录、验证码和上传页，但不上传文件；默认静默，排查时才加 `--visible`。
5. 使用 H 生成结果或普通视频目录时，运行 `adspower plan` 自动建立计划；已有 XLSX/CSV 时先运行 `adspower validate`。
6. 固定先运行 `preview`。它可以上传并填写表单，但不会点击最终发布按钮。
7. 只有预览成功且用户明确输入 `FABU`，才运行 `publish --publish-code FABU`。
8. 返回每个账号的状态、失败原因、日志和截图位置，然后显示 `protocol post-publish`。

## 生成后发布

当 H 刚完成批量或单次视频生成时，直接使用结果 JSON 中的 `output_root`：

```text
<launcher> adspower plan --video-root <output_root> --profile-no <环境编号> --start-at "YYYY-MM-DD HH:MM" --interval-minutes <分钟> --caption-template <模板> --hashtags <标签> [--attach-pid] [--timezone <时区>]
```

不得再次要求用户手动寻找生成视频。H 只收集状态为成功且文件头真实有效的视频；PNG/JPEG 改扩展名得到的假 MP4 必须拒绝。

多个 `--profile-no` 可重复传入。视频按账号轮流分配，同一环境内串行，不同环境并发。文案模板支持 `{pid}`、`{index}`、`{filename}`。

`--interval-minutes` 只能填 30 分钟的正整数倍，例如 30、60、90、120。计划完成后逐条核对返回的 `mappings`：每条必须包含视频、原 PID、账号和预约时间。

## 独立发布

普通视频目录也使用 `plan`。已有计划表直接预览：

```text
<launcher> adspower validate --input-file <计划表.xlsx或.csv>
<launcher> adspower preview --input-file <计划表.xlsx或.csv>
```

正式发布：

```text
<launcher> adspower publish --input-file <同一计划表> --publish-code FABU
```

默认工作目录为 `<home>/Desktop/H返回结果_发布/`。字段规范见 `references/schedule-schema.md`。

## 安全边界

- “测试”“检查”“预览”永远不等于正式发布。
- 使用 `--attach-pid` 时，每条视频都必须有完整数字 `商品PID`；任一项为空或非数字就整批停止建表。TikTok 只按该 PID 精确搜索并验证挂载，绝不按标题模糊搜索。
- API Key 只允许保存在工作目录 `config.json`，不得出现在日志、仓库或答复中。
- 登录失效、验证码、风控和人工验证会停止对应账号，其他账号继续。
- 最终 Schedule/Post 每项只点击一次；点击后核验失败不得自动重试。
- 首次真实发布先使用一个账号验证，再提高账号并发。
