# Security Policy

## 报告安全问题

如果你发现本仓库有敏感信息（API key / 账户 ID / 私钥等）意外泄露，或存在其它安全隐患，请**不要**开 public issue。

请通过以下方式联系维护者：

- GitHub issue（贴出问题类别但**不要**贴具体 secret 内容）
- 或邮件（联系仓库 owner，见 GitHub profile）

我们会在 48 小时内响应。

---

## 敏感信息管理原则

本仓库遵循以下规则确保 secret 不进入公开 git 历史：

### 1. 所有 secret 通过 `agents/secrets.local.json` 加载

- **模板**：`agents/secrets.example.json`（只放占位字符串）
- **实际**：`agents/secrets.local.json`（用户本地填真值，**已在 .gitignore**）
- **加载**：`agents/config.py` 里的 `_cfg()` 函数按 环境变量 > secrets.local.json > 默认空 顺序读取

### 2. `.gitignore` 覆盖

以下模式都被排除，永远不会进入 git：

```
agents/secrets.local.json
.env
.env.local
.env.*
!.env.example
*.secret
credentials.json
credentials.local.*
secrets/
*.pem
*.p12
*.pfx
id_rsa*
id_ed25519*
*.key
```

### 3. pre-commit hook 拦截

`.githooks/pre-commit` 自动扫描 staged 文件，命中以下模式即拒绝 commit：

- OpenAI API key (`sk-...`)
- Anthropic API key (`sk-ant-...`)
- GitHub Token (`ghp_...`, `gho_...`, 等)
- AWS Access Key (`AKIA...`)
- Google API Key (`AIza...`)
- Bearer token / Private key header
- 长十六进制字符串（32+ 字符，常见 API key 格式）

**贡献者第一次 clone 后必须启用 hook**：

```bash
git config core.hooksPath .githooks
```

或添加到 setup.bat / 首次运行脚本里。

### 4. 已核实无历史泄露

原维护者已通过 `git log -S` + `git log --all --pretty=format` 审计过全部 commit 历史，确认无真实 secret 曾经被 commit 过。initial commit `secrets.example.json` 里的 `FRED_API_KEY` 值是占位字符串 `YOUR_FRED_API_KEY_HERE_...`。

---

## 贡献者规则

提交 PR 时**禁止**：

- ❌ 硬编码任何真实 API key / token / 账户 ID / 密码
- ❌ commit `.env`、`secrets.local.json`、`credentials.*` 等文件
- ❌ 在 log / trace / issue 里贴出他人的真实 secret

请**遵守**：

- ✅ 用 `agents/secrets.example.json` 里的占位字符串或 `{{PLACEHOLDER}}` 表示 secret 位置
- ✅ 提到 API key 时说"你的 XXX key"而不是贴出具体值
- ✅ 用 `pre-commit` hook 前置检查

---

## 安全事件响应

如果不小心提交了真实 secret，**立刻**：

1. **撤销**该 key（在对应服务的 dashboard 里 revoke + 生成新的）
2. 从 git 历史彻底删除（不要只 `git rm`，历史里还有）：
   ```bash
   # 用 git-filter-repo（推荐，比 filter-branch 快）
   pip install git-filter-repo
   git filter-repo --path <file_containing_secret> --invert-paths
   git push --force origin main   # ⚠ 会重写远端历史
   ```
3. 通知所有 fork / clone 过的用户 rebase
4. 在 SECURITY.md 里记录事件（用于以后借鉴）

---

## 依赖安全

- 定期跑 `pip install --upgrade -r requirements.txt`（如有）
- moomoo OpenD 保持最新版
- 关注 yfinance / anthropic-sdk 等主要依赖的 CVE

---

## 变更历史

- **2026-07-27 初版**：审计确认历史干净，加 pre-commit hook + .gitignore 加固
