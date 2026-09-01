# HUST MSE Tutorial

这是一个面向华中科技大学机械相关同学的校园经验分享网站，使用 MkDocs Material 构建并发布到 GitHub Pages。

本站由学生发起和维护，不代表学校、学院、实验室或教师的官方立场。

## 本地预览

```bash
pip install -r requirements.txt
mkdocs serve
```

打开终端显示的本地地址查看网站。

## 生成静态网站

```bash
mkdocs build
```

生成结果会放在 `site/` 目录。

## 维护入口

- 网站配置：`mkdocs.yml`
- 首页：`docs/index.md`
- 关于页：`docs/about.md`
- 投稿说明：`docs/contribute.md`
- 内容政策：`docs/policies/content-policy.md`
- 隐私与 AI 处理：`docs/policies/privacy-ai.md`
- 勘误与撤回：`docs/policies/corrections.md`
- 模板文件：`docs/page-templates/`

## 内容维护原则

- 只把最终公开版本的文章和必要网页资源提交到 Git。
- 原始邮件、授权证明、未脱敏附件、模型日志和凭据不得进入公开仓库。
- 自动化工具只能提出发布建议或生成候选稿，不能绕过内容检查与可回滚发布流程。
- 对新增文章优先使用独立分支和 Pull Request，保留完整变更记录。
