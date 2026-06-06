"""
配置管理模块
============
从 config/monitor_config.json 加载监控配置，
从 .env 文件加载环境变量（API Keys、SMTP密码等），
提供统一的配置访问接口。
"""

import json
import os
from pathlib import Path
from typing import Optional
from functools import lru_cache

from dotenv import load_dotenv

# 自动加载 .env 文件（明确指定项目根目录路径）
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=True)


class Settings:
    """应用配置聚合类，管理所有配置项。"""

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置。

        Args:
            config_path: monitor_config.json 的路径，
                        默认为项目根目录下的 config/monitor_config.json
        """
        # 确定项目根目录
        self._project_root = Path(__file__).resolve().parent.parent.parent

        # 加载监控配置 JSON
        if config_path is None:
            config_path = self._project_root / "config" / "monitor_config.json"
        else:
            config_path = Path(config_path)

        with open(config_path, "r", encoding="utf-8") as f:
            self._config = json.load(f)

        # 数据目录
        data_dir = os.getenv("DATA_DIR", str(self._project_root / "data"))
        self.data_dir = Path(data_dir)
        self.raw_data_dir = self.data_dir / "raw"
        self.reports_dir = self.data_dir / "reports"

        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.raw_data_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ========== 监控范围 ==========

    @property
    def competitor_wechat(self) -> list[str]:
        """竞品公众号名称列表"""
        return self._config["monitor_scope"]["competitor_wechat"]

    @property
    def competitor_websites(self) -> list[dict]:
        """竞品官网列表 [{"name": "...", "url": "..."}]"""
        return self._config["monitor_scope"]["competitor_websites"]

    @property
    def industry_keywords(self) -> list[str]:
        """行业搜索关键词"""
        return self._config["monitor_scope"]["industry_keywords"]

    @property
    def news_sources(self) -> list[str]:
        """新闻来源平台"""
        return self._config["monitor_scope"]["news_sources"]

    # ========== 调度配置 ==========

    @property
    def schedule_config(self) -> dict:
        """定时任务配置"""
        return self._config["schedule"]

    # ========== 通知配置 ==========

    @property
    def email_recipients(self) -> list[str]:
        """邮件接收者列表"""
        return self._config["notification"]["email_recipients"]

    @property
    def smtp_config(self) -> dict:
        """SMTP 配置（密码从环境变量读取）"""
        return {
            "host": os.getenv("SMTP_HOST", self._config["notification"]["smtp_host"]),
            "port": int(os.getenv("SMTP_PORT", self._config["notification"]["smtp_port"])),
            "user": os.getenv("SMTP_USER", ""),
            "password": os.getenv("SMTP_PASSWORD", ""),
            "from": os.getenv("SMTP_FROM", "AI情报员工 <notify@pudow.com>"),
        }

    @property
    def wechat_bot_webhook(self) -> str:
        """企业微信机器人 Webhook URL"""
        return os.getenv("WECHAT_BOT_WEBHOOK", self._config["notification"].get("wechat_bot_webhook", ""))

    # ========== 公司背景 ==========

    @property
    def company_context(self) -> dict:
        """朴道水汇公司背景信息（用于 AI Prompt）"""
        return self._config["company_context"]

    # ========== 爬虫配置 ==========

    @property
    def crawler_settings(self) -> dict:
        """爬虫参数配置"""
        return self._config["crawler_settings"]

    # ========== AI 配置 ==========

    @property
    def ai_settings(self) -> dict:
        """AI / LLM 调用参数"""
        return self._config["ai_settings"]

    @property
    def anthropic_api_key(self) -> str:
        """Anthropic API Key（从环境变量读取）"""
        return os.getenv("ANTHROPIC_API_KEY", "")

    # ========== 过滤规则 ==========

    @property
    def filter_rules(self) -> dict:
        """内容过滤规则（白名单、黑名单等）"""
        return self._config.get("filter_rules", {})

    @property
    def keyword_whitelist(self) -> list[str]:
        """关键词白名单"""
        return self.filter_rules.get("keyword_whitelist", [])

    @property
    def competitor_blacklist(self) -> list[str]:
        """竞品内容黑名单（不相关品类关键词）"""
        return self.filter_rules.get("competitor_blacklist", [])

    @property
    def max_news_age_days(self) -> int:
        """新闻最大时效（天）"""
        return self.filter_rules.get("max_news_age_days", 14)

    @property
    def title_similarity_threshold(self) -> float:
        """标题去重相似度阈值"""
        return self.filter_rules.get("title_similarity_threshold", 0.8)

    # ========== 路径属性 ==========

    @property
    def db_path(self) -> str:
        """SQLite 数据库路径"""
        return str(self.data_dir / "intelligence.db")

    @property
    def project_root(self) -> Path:
        """项目根目录"""
        return self._project_root

    @property
    def templates_dir(self) -> Path:
        """模板目录"""
        return self._project_root / "templates"

    def validate(self) -> list[str]:
        """验证配置完整性，返回缺失/错误的列表。"""
        errors = []

        # 检查 API Key
        if not self.anthropic_api_key:
            errors.append("缺少 ANTHROPIC_API_KEY 环境变量")

        # 检查监控对象
        if not self.competitor_wechat:
            errors.append("competitor_wechat 列表为空")
        if not self.competitor_websites:
            errors.append("competitor_websites 列表为空")
        if not self.industry_keywords:
            errors.append("industry_keywords 列表为空")

        # 检查通知配置
        if not self.email_recipients:
            errors.append("email_recipients 列表为空")

        return errors


@lru_cache()
def get_settings(config_path: Optional[str] = None) -> Settings:
    """获取全局唯一的 Settings 实例（带缓存）。"""
    return Settings(config_path)
