# 🚀 Termux → 阿里云 ECS 完整迁移方案

## 📋 当前 Termux 上的组件清单

| 组件 | 说明 | 状态 |
|------|------|------|
| **Hermes Agent** v0.13.0 | AI助手，pip安装，Python 3.13 | 迁移到云 |
| **公务车管理系统** | Flask + SQLite，849K | 迁移到云 |
| **糖价采集系统** | Python脚本 + cron，20K数据 | 迁移到云 |
| **农业贸易日报** | cron job，每日9点 | 迁移到云 |
| **Himalaya 邮件** | QQ邮箱SMTP/IMAP | 迁移到云 |
| **Telegram/Discord** | Hermes gateway | 迁移到云 |

## 🏗️ 阿里云目标架构

```
阿里云 ECS (Ubuntu 22.04/24.04)
├── Nginx (反向代理 + HTTPS)
│   ├── 252546987.xyz → 公务车管理系统 (Gunicorn)
│   └── hermes.252546987.xyz → Hermes WebUI (可选)
├── Gunicorn (公务车系统 WSGI)
│   └── Flask app × 4 workers
├── Hermes Agent (systemd service)
│   ├── Telegram Gateway
│   ├── Cron: 农业贸易日报 (每日9点)
│   └── Cron: 糖价采集 (工作日9点)
├── Himalaya (邮件CLI)
├── SQLite 数据库 (公务车 + 糖价)
└── Let's Encrypt SSL (certbot)
```

## 📦 迁移内容

### 1. Hermes Agent
- pip install hermes-agent
- 迁移 ~/.hermes/config.yaml (API keys, providers, toolsets)
- 迁移 ~/.hermes/cron/jobs.json (定时任务)
- 迁移自定义 skills (agri-trade-news-daily, sugar-price-collector)
- 迁移 memory (用户偏好、配置信息)
- 迁移 Telegram/Discord gateway 配置

### 2. 公务车管理系统
- 去除 PA 特有 hack (30秒超时绕过、DB轮询等)
- 改为标准 Gunicorn 部署 (4 workers, 120s timeout)
- Nginx 反向代理 + HTTPS
- systemd 管理 Gunicorn 进程
- 数据库迁移 (SQLite → 可选 PostgreSQL)

### 3. 糖价采集系统
- 复制脚本和数据
- 配置 cron job

### 4. 邮件系统
- 安装 himalaya
- 复制配置文件

## ⚡ 阿里云 vs PA 的提升

| 项目 | PythonAnywhere 免费版 | 阿里云 ECS |
|------|----------------------|------------|
| 请求超时 | 30秒硬限制 | 无限制 |
| WSGI Workers | 单进程 | 4+ workers |
| 定时任务 | 仅1个/天 | 无限制 cron |
| AI分析 | 必须异步start+poll | 直接同步返回 |
| 自定义域名 | 需付费 | 免费 Let's Encrypt |
| SSL | 有限制 | certbot 自动续期 |
| SSH | 无 | 完整控制 |
| 存储 | 512MB | 按需 |
| 数据库 | SQLite | SQLite/PostgreSQL |

## 🔧 代码修改要点

### 公务车系统 (app.py)
1. **移除异步AI分析** — 改回同步（不再受30秒限制）
2. **移除DB轮询fallback** — 多worker模式由Gunicorn管理
3. **移除PA特有的.env多路径查找** — 改为标准环境变量
4. **SESSION_COOKIE_SECURE** — 保留（阿里云也用HTTPS）
5. **添加 Gunicorn 入口** — wsgi.py

### Hermes Agent
1. **安装方式** — pip install (Linux x86_64，不再受限Termux的ARM/编译限制)
2. **可用更多模型** — 不再受PA 429限流影响
3. **mem0 SDK** — 可以直接安装（不再有numpy编译超时问题）
4. **Cron** — 使用 Hermes 内置 cron 或系统 crontab

## 📋 服务器最低配置要求

| 项目 | 最低 | 推荐 |
|------|------|------|
| CPU | 1核 | 2核 |
| 内存 | 1GB | 2GB |
| 硬盘 | 20GB | 40GB |
| 带宽 | 1Mbps | 5Mbps |
| 系统 | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |

> 💰 阿里云 2核2G 轻量应用服务器约 ¥50/月，新用户首年更低
