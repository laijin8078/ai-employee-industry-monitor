"""
微信公众号爬虫（可用性优先）
=============================
策略：持久化 Cookie Playwright → 搜索引擎检索兜底 → 缓存降级
- 不做验证码破解、不高频请求、不绕过登录风控
- 微信采不到不阻塞流水线，只作为增强源
- 搜索引擎检索 mp.weixin.qq.com 作为补偿
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup
from loguru import logger

from .base import BaseCrawler
from .browser_fetcher import BrowserFetcher
from ..models.schemas import RawItem


class WechatCrawler(BaseCrawler):
    """微信公众号文章采集器（可用性优先）"""

    CHANNEL = "wechat"

    def __init__(self, settings, cache_dir: Path):
        super().__init__(settings, cache_dir)
        self.time_range_days = settings.max_news_age_days
        self._browser: Optional[BrowserFetcher] = None
        self.profile_dir = Path(__file__).resolve().parent.parent.parent / "data" / "browser_profiles" / "wechat"

    @property
    def browser(self) -> BrowserFetcher:
        if self._browser is None:
            headless = self.crawler_config.get("headless", True)
            self._browser = BrowserFetcher(
                headless=headless,
                timeout_ms=30000,
                user_data_dir=str(self.profile_dir) if self.profile_dir.exists() else None,
            )
        return self._browser

    def crawl(
        self,
        accounts: list[str],
        time_range_days: int = None,
    ) -> list[RawItem]:
        """
        采集微信公众号文章（可用性优先）。

        策略：
        1. 如果有持久化 Profile → Playwright 尝试搜狗微信
        2. 如果没 Profile 或 Playwright 失败 → 搜索引擎检索公众号文章
        3. 都失败 → 缓存兜底
        """
        if time_range_days is None:
            time_range_days = self.time_range_days

        cutoff_date = datetime.now() - timedelta(days=time_range_days)
        all_items = []

        # 判断微信采集能力
        can_use_playwright = self.browser.is_available
        has_profile = self.profile_dir.exists()

        logger.info(
            f"[微信爬虫] 开始采集 {len(accounts)} 个公众号 "
            f"(Playwright: {'有' if can_use_playwright else '无'}, "
            f"Profile: {'有' if has_profile else '无'})"
        )

        for account_name in accounts:
            items = []

            # Level 1: 有 Profile 就用 Playwright 尝试搜狗微信
            if can_use_playwright and has_profile:
                items = self._crawl_via_playwright(account_name, cutoff_date)

            # Level 2: Playwright 失败或无 Profile → 搜索引擎检索
            if not items:
                logger.info(f"   [{account_name}] 微信直采失败/不可用，启用搜索引擎补偿...")
                items = self._crawl_via_search_engine(account_name, cutoff_date)

            # Level 3: 缓存降级
            if not items:
                cached = self.load_cached_data(f"{self.CHANNEL}_{account_name}")
                if cached:
                    logger.info(f"   [{account_name}] 使用缓存数据（{len(cached)}条）")
                    items = cached

            if items:
                all_items.extend(items)
                logger.info(f"[微信爬虫] {account_name}: {len(items)} 篇")
            else:
                logger.warning(f"[微信爬虫] {account_name}: 本期无数据")

        if all_items:
            self.cache_raw_data(all_items, f"{self.CHANNEL}_all")

        return all_items

    def _crawl_via_playwright(
        self, account_name: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """通过 Playwright 访问搜狗微信搜索"""
        try:
            search_url = f"https://weixin.sogou.com/weixin?type=1&query={account_name}"
            result = self.browser.fetch_html(search_url)

            if result["html"] and "请输入验证码" not in result["html"]:
                return self._parse_sogou_html(result["html"], account_name, cutoff_date)
            elif "请输入验证码" in result.get("html", ""):
                logger.warning(f"   [{account_name}] 触发验证码，需人工刷新 Cookie")
            else:
                logger.debug(f"   [{account_name}] Playwright 采集为空")
        except Exception as e:
            logger.debug(f"   [{account_name}] Playwright 异常: {e}")

        return []

    def _crawl_via_search_engine(
        self, account_name: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """
        通过搜索引擎检索微信公众号文章。
        搜 "安吉尔 site:mp.weixin.qq.com 净水"
        """
        items = []
        queries = [
            f"{account_name} site:mp.weixin.qq.com",
            f"{account_name} 净水 site:mp.weixin.qq.com 新品",
            f"{account_name} site:mp.weixin.qq.com 发布",
        ]

        for query in queries[:2]:  # 限制每次的搜索次数
            try:
                url = f"https://www.baidu.com/s?wd={query}"
                html = self.fetch(url, timeout=15)
                if html:
                    parsed = self._parse_baidu_wechat_results(html, account_name, cutoff_date)
                    items.extend(parsed)
            except Exception as e:
                logger.debug(f"   搜索引擎检索失败: {e}")

        return items

    def _parse_sogou_html(
        self, html: str, account_name: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """解析搜狗微信搜索结果"""
        soup = BeautifulSoup(html, "lxml")
        items = []
        news_items = soup.select("li.news-item, .news-list li, ul.news-list2 li, .txt-box")

        for elem in news_items:
            try:
                title_tag = elem.select_one("h3 a, .tit a, a[href*='mp.weixin']")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")
                summary_tag = elem.select_one(".txt-info, p, .s3")
                summary = summary_tag.get_text(strip=True) if summary_tag else ""
                time_tag = elem.select_one(".s2, .time, time")
                time_str = time_tag.get_text(strip=True) if time_tag else ""
                publish_date = self._parse_wechat_time(time_str)

                if publish_date and publish_date < cutoff_date:
                    continue

                items.append(RawItem(
                    source_channel=self.CHANNEL, source_name=account_name,
                    title=title, url=url, content=summary,
                    publish_date=publish_date,
                    raw_metadata={"account": account_name, "method": "sogou"},
                ))
            except Exception:
                continue

        return items

    def _parse_baidu_wechat_results(
        self, html: str, account_name: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """解析百度搜索结果中的微信公众号文章"""
        soup = BeautifulSoup(html, "lxml")
        items = []
        for elem in soup.select(".result, .c-container")[:10]:
            try:
                title_tag = elem.select_one("h3 a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")
                if "mp.weixin.qq.com" not in url:
                    continue
                summary_tag = elem.select_one(".c-abstract, .c-span-last, .content")
                summary = summary_tag.get_text(strip=True)[:200] if summary_tag else ""
                items.append(RawItem(
                    source_channel=self.CHANNEL, source_name=account_name,
                    title=title, url=url, content=summary,
                    publish_date=datetime.now(),
                    raw_metadata={"account": account_name, "method": "baidu_search"},
                ))
            except Exception:
                continue
        return items

    def _parse_wechat_time(self, time_str: str) -> datetime:
        """解析微信文章时间格式"""
        if not time_str:
            return datetime.now()
        time_str = time_str.strip()
        if "今天" in time_str:
            return datetime.now()
        if "昨天" in time_str:
            return datetime.now() - timedelta(days=1)
        days_match = re.search(r"(\d+)天前", time_str)
        if days_match:
            return datetime.now() - timedelta(days=int(days_match.group(1)))
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue
        return datetime.now()

    def open_profile_session(self) -> bool:
        """
        手动打开有界面的浏览器会话，完成微信搜狗验证后保存 Cookie。
        在终端运行：
            python -c "from src.crawlers.wechat import WechatCrawler; ..."
        按回车保存会话。
        """
        if not self.browser.is_available:
            logger.error("Playwright 未安装，无法创建会话")
            return False

        self.profile_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Profile 目录: {self.profile_dir}")
        logger.info("正在打开微信搜狗，请在浏览器中完成验证...")

        fetcher = BrowserFetcher(
            headless=False,
            timeout_ms=60000,
            user_data_dir=str(self.profile_dir),
        )
        fetcher.fetch_html("https://weixin.sogou.com/")

        logger.info("会话已保存。后续定时任务将使用此 Profile。")
        return True
