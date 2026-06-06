# 🔍 竞品与行业动态情报AI员工

> 为朴道水汇（净水器公司，主营DPM纳滤技术）构建的AI员工系统。  
> 每两周自动爬取竞品公众号、官网、行业新闻，使用AI分析整理后生成结构化情报报告。

## ✨ 功能概览

- **多渠道并行采集**：微信公众号 + 竞品官网 + 行业新闻（今日头条/腾讯新闻/新浪财经）
- **AI智能分析**：Claude API 驱动的初筛分类 + 深度战略分析
- **结构化报告**：JSON 数据报告 + HTML 邮件报告
- **自动通知**：邮件发送（高优先级即时告警）+ 企业微信机器人
- **数据持久化**：SQLite 存储最近12期数据，支持趋势分析
- **定时调度**：APScheduler 每两周自动执行
- **健壮容错**：缓存回退、重试机制、规则兜底

## 📁 项目结构

```
ai-employee/
├── src/
│   ├── main.py              # 主流程编排 + CLI 入口
│   ├── config/
│   │   └── settings.py      # 统一配置管理
│   ├── models/
│   │   └── schemas.py       # Pydantic 数据模型
│   ├── crawlers/            # 爬虫模块
│   │   ├── base.py          # 爬虫基类（请求/缓存/重试）
│   │   ├── wechat.py        # 微信公众号爬虫
│   │   ├── website.py       # 竞品官网爬虫
│   │   └── news.py          # 行业新闻爬虫
│   ├── processors/
│   │   └── cleaner.py       # 数据清洗/去重/过滤
│   ├── analyzers/           # AI 分析模块
│   │   ├── llm_client.py    # LLM API 客户端
│   │   ├── screener.py      # AI 初筛（相关性/分类/优先级）
│   │   └── deep_analyzer.py # AI 深度分析（影响/对策）
│   ├── reporters/           # 报告生成
│   │   ├── json_reporter.py # JSON 报告
│   │   └── html_reporter.py # HTML 邮件报告
│   ├── notifiers/
│   │   └── email_notifier.py# 邮件/企微通知
│   └── storage/
│       └── database.py      # SQLite 数据库
├── config/
│   └── monitor_config.json  # 监控对象配置
├── templates/
│   └── report.html          # HTML 报告模板
├── data/                    # 运行数据（自动创建）
│   ├── raw/                 # 原始数据缓存
│   ├── reports/             # 生成的报告
│   └── intelligence.db      # SQLite 数据库
├── requirements.txt
└── .env.template            # 环境变量模板
```

## 🚀 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone <repo-url>
cd ai-employee

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（用于动态页面爬取）
playwright install chromium
```

### 2. 配置

```bash
# 复制环境变量模板
cp .env.template .env

# 编辑 .env，填入必要的信息：
#   ANTHROPIC_API_KEY=sk-ant-...    (必须)
#   SMTP_HOST=...                   (邮件通知，必须)
#   SMTP_PASSWORD=...               (邮件通知，必须)
```

编辑 `config/monitor_config.json`，调整监控范围（公众号、官网、关键词等）。

### 3. 运行

```bash
# 验证配置
python -m src.main --validate

# 使用模拟数据测试（不需要网络和API Key）
python -m src.main --mock

# 执行一次真实情报采集
python -m src.main --once

# 启动定时调度（每两周执行）
python -m src.main --schedule
```

## 📊 输出示例

运行后会在 `data/reports/` 目录生成报告文件：

- `intelligence_report_2026-06-06.json` — 结构化 JSON 数据
- `intelligence_report_2026-06-06.html` — 可读的 HTML 邮件报告

报告内容包含：
- **本期摘要**：核心发现一句话总结
- **分类情报**：竞品动态 / 行业政策 / 行业动态 / 技术突破
- **每条情报含**：AI摘要、影响分析、应对策略建议、紧急度评分
- **竞品汇总**：每个竞品的本期动态概况
- **综合建议**：AI 生成的对朴道的战略建议

## 🔧 配置说明

### 监控范围 (`monitor_config.json`)

| 配置项 | 说明 | 示例 |
|--------|------|------|
| `competitor_wechat` | 竞品公众号名称 | `["美的净水", "沁园净水器官方"]` |
| `competitor_websites` | 竞品官网新闻页 | `[{"name":"美的", "url":"..."}]` |
| `industry_keywords` | 行业搜索关键词 | `["净水器新国标", "纳滤技术"]` |
| `news_sources` | 新闻平台 | `["今日头条", "新浪财经"]` |

### 环境变量 (`.env`)

| 变量 | 必须 | 说明 |
|------|------|------|
| `ANTHROPIC_API_KEY` | ✅ | Anthropic Claude API Key |
| `SMTP_HOST` | ✅ | 邮件 SMTP 服务器 |
| `SMTP_PASSWORD` | ✅ | 邮件密码 |
| `WECHAT_BOT_WEBHOOK` | ❌ | 企业微信机器人 Webhook |
| `HTTP_PROXY` | ❌ | 代理配置 |

## 📐 处理流程

```
定时触发 (每两周周一 09:00)
    │
    ├─ [并行] 微信公众号爬取 ─┐
    ├─ [并行] 竞品官网爬取 ──┤
    └─ [并行] 行业新闻搜索 ──┘
              │
    ┌─────────▼─────────┐
    │   数据清洗与去重    │  ← 标题相似度去重、黑名单过滤、时效检查
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │   AI 初筛         │  ← 判断相关性、分类、优先级
    └─────────┬─────────┘
              │ (相关 + 非低优先级)
    ┌─────────▼─────────┐
    │   AI 深度分析      │  ← 摘要、影响分析、应对策略、紧急度评分
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │   生成报告         │  ← JSON + HTML/PDF
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │   发送通知         │  ← 邮件 + 企业微信
    └─────────┬─────────┘
              │
    ┌─────────▼─────────┐
    │   数据归档         │  ← SQLite 存储 + 旧数据清理
    └───────────────────┘
```

## 🛡️ 容错机制

| 场景 | 处理策略 |
|------|----------|
| 公众号停更 | 标记"14天无更新"，提示人工检查 |
| 爬取失败 | 使用上次缓存 + 标记"数据不完整" |
| LLM API 不可用 | 关键词规则兜底（基础分类和优先级判断） |
| 单渠道失败 | 其他渠道继续，不影响整体流程 |
| 连续3次失败 | 发送告警通知 |
| 无数据 | 发送"本期无重大动态"简要邮件 |

## 📈 版本路线

- **V1 (MVP)** ✅ 当前版本
  - 3个公众号 + 2个官网 + 行业新闻
  - AI 初筛 + 深度分析
  - JSON + HTML 报告
  - 邮件通知

- **V2** (规划中)
  - 京东/天猫价格监控
  - 微博/小红书/抖音扩展
  - 竞品对比表自动生成

- **V3** (规划中)
  - 趋势分析（基于3个月数据）
  - 预测性分析

- **V4** (规划中)
  - 智能应对方案生成
  - OA 系统对接

## 📄 License

内部项目，朴道水汇版权所有。
