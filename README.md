# JD Video Publisher

一个安全闸门优先的京东短视频发布工作流：本地视频抽帧、商品 SKU 匹配、飞书人工审核、京东定时发布。

> 本项目是社区开源工具，与京东、飞书或 OpenAI 无官方隶属关系。后台页面可能变化，正式发布前必须人工复核。

## 核心特性

- 用 FFmpeg 在本地抽取视频帧，不上传原始素材。
- 按商品家族匹配 1–10 个 SKU，对模糊结果要求人工复核。
- 把标题、SKU、话题、标签和时间同步到飞书审核表。
- 只有“已批准”且定时时间合规的任务才能进入发布队列。
- 京东页面流程默认支持预演模式；验证码、登录失效或页面异常时立即停止。

## 快速开始

要求：Windows、Python 3.11+、FFmpeg，以及已授权的飞书应用。

```powershell
Copy-Item config.example.json config.json
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

编辑 `config.json`，设置你自己的素材目录、商品导出文件、话题和标签。不要把凭证直接写进可提交的配置文件。

把飞书凭证保存为 `.secrets/feishu.json`：

```json
{
  "app_id": "YOUR_APP_ID",
  "app_secret": "YOUR_APP_SECRET",
  "app_token": "YOUR_APP_TOKEN",
  "table_id": "YOUR_TABLE_ID"
}
```

`.secrets/` 、`config.json`、商品表、视频和所有生成结果均被 Git 忽略。

## 工作流

1. 运行 `run_phase1.py`，扫描视频、抽帧并生成待审核数据。
2. 在飞书中人工核对标题、SKU、时间和内容相关性。
3. 把审核状态设为“已批准”。
4. 运行 `run_phase2.py` 生成可发布队列。
5. 先以 `commit=false` 预演京东表单，确认无误后再由维护者明确执行提交。

## 安全边界

- 不绕过验证码、滑块、登录或账号安全控制。
- 不提交 Cookie、Token、商家凭证、真实商品库、视频、封面或运行日志。
- 不用自动化结果取代内容合规和 SKU 相关性审核。
- 正式发布会改变外部状态，应在提交前进行人工确认。

详细报告漏洞方式见 [SECURITY.md](SECURITY.md)。

## 贡献

欢迎提交 Issue 和 Pull Request。修改发布页面选择器时，请附带脱敏的页面结构说明和对应测试，不要附真实账号数据。

## 许可证

[MIT](LICENSE)
