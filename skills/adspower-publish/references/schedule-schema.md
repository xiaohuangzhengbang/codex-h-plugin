# 计划表规范

推荐文件：`schedule.xlsx`，工作表名：`发布计划`。也兼容 UTF-8 CSV。

| 字段 | 必填 | 说明 |
|---|---:|---|
| `启用` / `enabled` | 是 | `yes` 执行，`no` 跳过 |
| `环境编号` / `profileNo` | 是 | AdsPower 环境编号 |
| `视频路径` / `videoPath` | 是 | 本地视频绝对路径 |
| `文案` / `caption` | 否 | TikTok 正文 |
| `标签` / `hashtags` | 否 | 空格分隔的标签，程序会与正文合并 |
| `商品PID` / `productPid` | 否 | TikTok Shop 完整数字 PID；插件只按 PID 精确搜索并挂车 |
| `预定时间` / `scheduledAt` | 是 | Excel日期时间或 `YYYY-MM-DD HH:mm` |
| `时区` / `timezone` | 建议 | IANA 时区，如 `America/Mexico_City`；`预定时间` 按该 AdsPower 账号 TikTok Studio 显示的本地时间填写 |
| `发布模式` | 是 | `schedule` 正式排期，`draft` 只填写不提交 |
| `任务ID` / `taskId` | 否 | 每行稳定标识；H 自动生成计划时会写入 |

示例：

```csv
enabled,profileNo,videoPath,caption,hashtags,scheduledAt
yes,27,C:/Videos/a.mp4,夏季清凉好物,#TikTokShop #Summer,2026-08-01 10:30
```

CSV 中包含逗号的文案必须使用双引号包围。

`preview` 会上传并填写计划，但不会点击最终 Schedule/Post。正式发布必须在同一计划预览成功后输入 `FABU`。同一环境内任务串行，不同环境并发；登录、验证码或风控只停止对应环境。
