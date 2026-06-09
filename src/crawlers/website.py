"""
竞品官网爬虫（两级策略）
========================
策略：requests 优先 → Playwright 浏览器兜底 → 缓存降级
- 快的网站用 requests（安吉尔），不浪费浏览器资源
- 难采的网站（美的/沁园 SSL 阻断）自动启用 Playwright
- Playwright 失败也不阻塞流水线
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

from .base import BaseCrawler
from .browser_fetcher import BrowserFetcher
from ..models.schemas import RawItem


class WebsiteCrawler(BaseCrawler):
    """竞品官网新闻采集器（两级策略）"""

    CHANNEL = "website"

    def __init__(self, settings, cache_dir: Path):
        super().__init__(settings, cache_dir)
        self.time_range_days = settings.max_news_age_days
        self._browser: Optional[BrowserFetcher] = None

    @property
    def browser(self) -> BrowserFetcher:
        """懒加载浏览器采集器"""
        if self._browser is None:
            headless = self.crawler_config.get("headless", True)
            self._browser = BrowserFetcher(headless=headless, timeout_ms=30000)
        return self._browser

    def crawl(
        self,
        sites: list[dict],
        time_range_days: int = None,
    ) -> list[RawItem]:
        """
        爬取竞品官网新闻列表（两级策略）。

        Args:
            sites: [{"name": "美的净水", "url": "https://water.midea.com/news/"}]
            time_range_days: 时间范围
        """
        if time_range_days is None:
            time_range_days = self.time_range_days

        cutoff_date = datetime.now() - timedelta(days=time_range_days)
        all_items = []

        logger.info(f"[官网爬虫] 开始采集 {len(sites)} 个网站（requests优先→Playwright兜底）")

        for site in sites:
            site_name = site["name"]
            site_url = site["url"]

            items = self._crawl_with_fallback(site_name, site_url, cutoff_date)
            all_items.extend(items)
            logger.info(f"[官网爬虫] {site_name}: {len(items)} 条")

        if all_items:
            self.cache_raw_data(all_items, f"{self.CHANNEL}_all")

        return all_items

    def _crawl_with_fallback(
        self, site_name: str, site_url: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """
        三级采集策略：
        1. requests（快，无浏览器开销）→ 含 SSLError 自动升级到 Playwright
        2. Playwright 浏览器兜底
        3. 最近 7 天缓存降级
        """
        strategy_used = "requests"
        fallback_used = False

        # === Level 1: requests ===
        html = self.fetch(site_url, source_name=site_name)
        if html and len(html) > 1000:
            items = self._parse_news_html(html, site_name, site_url, cutoff_date)
            if items:
                self.record_source_health(site_name, "ok", len(items))
                return items

        # === Level 2: Playwright 浏览器兜底 ===
        if self.browser.is_available:
            strategy_used = "playwright"
            fallback_used = True
            logger.info(f"   [{site_name}] requests 失败（SSL/反爬），启用 Playwright...")
            result = self.browser.fetch_html(site_url, wait_selector=None)
            if result["html"] and len(result["html"]) > 1000:
                items = self._parse_news_html(
                    result["html"], site_name, site_url, cutoff_date
                )
                if items:
                    self.record_source_health(site_name, "ok", len(items), fallback_used=True)
                    logger.info(f"   [{site_name}] Playwright 成功: {len(items)} 条")
                    return items

            logger.warning(f"   [{site_name}] Playwright 失败: {result.get('error', '未知')[:80]}")
        else:
            logger.info(f"   [{site_name}] Playwright 未安装，跳过浏览器兜底")

        # === Level 3: 最近 7 天缓存降级 ===
        cached = self.load_cached_data_recent(f"{self.CHANNEL}_{site_name}", max_age_days=7)
        if cached:
            strategy_used = "cache"
            fallback_used = True
            self.record_source_health(site_name, "degraded", len(cached),
                                       error=strategy_used, fallback_used=True)
            logger.info(f"   [{site_name}] 使用缓存兜底（{len(cached)}条）")
            for c in cached:
                c.raw_metadata["source_health"] = strategy_used
            return cached

        self.record_source_health(site_name, "failed", 0,
                                   error="所有策略均失败", fallback_used=fallback_used)
        logger.warning(f"   [{site_name}] 所有策略均失败")
        return []

    def _parse_news_html(
        self, html: str, site_name: str, base_url: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """解析网站新闻列表页 HTML"""
        soup = BeautifulSoup(html, "lxml")
        items = []

        # 多种常见的新闻列表选择器
        news_selectors = [
            ".news-item", ".news-list li", ".article-list li", ".list-item",
            ".news-box .item", "article", ".dynamic-list > div",
            ".content-list > li", ".post-item", ".news-list .item",
            "a[href*='news']", "a[href*='detail']", "a[href*='article']",
        ]

        news_elements = []
        for selector in news_selectors:
            found = soup.select(selector)
            if len(found) > len(news_elements):
                news_elements = found

        if not news_elements:
            # 通用：找所有带链接且有足够文本的元素
            news_elements = [
                el for el in soup.select("a[href]")
                if len(el.get_text(strip=True)) > 8
            ]

        for element in news_elements:
            try:
                item = self._parse_news_element(element, site_name, base_url, cutoff_date)
                if item:
                    items.append(item)
            except Exception:
                continue

        return items

    def _parse_news_element(
        self, element, site_name: str, base_url: str, cutoff_date: datetime,
    ) -> Optional[RawItem]:
        """解析单个新闻条目"""
        # 标题
        title_tag = element
        if element.name != "a":
            title_tag = element.select_one("a, h2, h3, h4, .title, .news-title")

        if title_tag and title_tag.name == "a":
            title = title_tag.get_text(strip=True)
            url = urljoin(base_url, title_tag.get("href", ""))
        elif title_tag:
            title = title_tag.get_text(strip=True)
            link = element.select_one("a")
            url = urljoin(base_url, link.get("href", "")) if link else base_url
        else:
            title = element.get_text(strip=True)[:100]
            url = element.get("href", base_url) if hasattr(element, "get") else base_url

        if not title or len(title) < 5:
            return None

        # 过滤无关内容
        skip_words = ["关于我们", "联系我们", "公司简介", "法律声明", "隐私政策"]
        if any(w in title for w in skip_words):
            return None

        # 摘要和日期
        parent = element.parent if hasattr(element, "parent") and element.parent else element
        full_text = parent.get_text(strip=True) if hasattr(parent, "get_text") else title
        summary = full_text[:300]

        time_tag = (
            element.select_one(".time, .date, time, .pub-date, span[class*='time'], span[class*='date']")
            if hasattr(element, "select_one") else None
        )
        time_str = time_tag.get_text(strip=True) if time_tag else ""
        publish_date = self._parse_news_time(time_str)

        if not publish_date or publish_date < cutoff_date:
            return None

        return RawItem(
            source_channel=self.CHANNEL,
            source_name=site_name,
            title=title,
            url=url,
            content=summary,
            publish_date=publish_date,
            raw_metadata={"site_url": base_url},
        )

    def _parse_news_time(self, time_str: str) -> Optional[datetime]:
        """解析新闻发布时间"""
        if not time_str:
            return None
        time_str = time_str.strip()
        if "今天" in time_str:
            return datetime.now()
        if "昨天" in time_str:
            return datetime.now() - timedelta(days=1)
        days_match = re.search(r"(\d+)\s*天前", time_str)
        if days_match:
            return datetime.now() - timedelta(days=int(days_match.group(1)))
        for fmt in ["%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y/%m/%d", "%Y年%m月%d日", "%m-%d", "%m月%d日"]:
            try:
                dt = datetime.strptime(time_str, fmt)
                if dt.year == 1900:
                    dt = dt.replace(year=datetime.now().year)
                    if dt > datetime.now() + timedelta(days=1):
                        dt = dt.replace(year=dt.year - 1)
                return dt
            except ValueError:
                continue
        return self.parse_chinese_datetime(time_str)
