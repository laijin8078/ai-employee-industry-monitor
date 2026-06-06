"""
竞品官网爬虫
===========
爬取竞品官网的新闻/动态页面，
支持静态 HTML 解析和 Playwright 动态页面。
"""

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from loguru import logger

from .base import BaseCrawler
from ..models.schemas import RawItem


class WebsiteCrawler(BaseCrawler):
    """竞品官网新闻采集器"""

    CHANNEL = "website"

    def __init__(self, settings, cache_dir: Path):
        super().__init__(settings, cache_dir)
        self.time_range_days = settings.max_news_age_days

    def crawl(
        self,
        sites: list[dict],
        time_range_days: int = None,
    ) -> list[RawItem]:
        """
        爬取竞品官网新闻列表。

        Args:
            sites: 网站列表 [{"name": "美的净水", "url": "https://water.midea.com/news/"}]
            time_range_days: 时间范围

        Returns:
            RawItem 列表
        """
        if time_range_days is None:
            time_range_days = self.time_range_days

        cutoff_date = datetime.now() - timedelta(days=time_range_days)
        all_items = []

        logger.info(f"[官网爬虫] 开始采集 {len(sites)} 个网站")

        for site in sites:
            site_name = site["name"]
            site_url = site["url"]

            try:
                items = self._crawl_site(site_name, site_url, cutoff_date)
                all_items.extend(items)
                logger.info(f"[官网爬虫] {site_name}: 获取 {len(items)} 条新闻")
            except Exception as e:
                logger.error(f"[官网爬虫] {site_name} 爬取失败: {e}")
                # 缓存回退
                cached = self.load_cached_data(f"{self.CHANNEL}_{site_name}")
                if cached:
                    logger.info(f"[官网爬虫] {site_name}: 使用缓存数据（{len(cached)}条）")
                    all_items.extend(cached)

        if all_items:
            self.cache_raw_data(all_items, f"{self.CHANNEL}_all")

        return all_items

    def _crawl_site(
        self, site_name: str, base_url: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """爬取单个网站的新闻列表页"""
        html = self.fetch(base_url)
        if not html:
            logger.warning(f"[官网爬虫] 无法访问 {base_url}")
            return []

        soup = BeautifulSoup(html, "lxml")
        items = []

        # 尝试多种常见的新闻列表选择器
        news_selectors = [
            ".news-item",
            ".news-list li",
            ".article-list li",
            ".list-item",
            ".news-box .item",
            "article",
            ".dynamic-list > div",
            ".content-list > li",
            ".post-item",
        ]

        news_elements = []
        for selector in news_selectors:
            news_elements = soup.select(selector)
            if news_elements:
                break

        # 如果都没匹配到，尝试找所有包含链接的元素
        if not news_elements:
            logger.debug(f"[官网爬虫] {site_name}: 未匹配标准选择器，尝试通用解析")
            news_elements = soup.select("a[href*='news'], a[href*='detail'], a[href*='article']")

        for element in news_elements:
            try:
                item = self._parse_news_element(element, site_name, base_url, cutoff_date)
                if item:
                    items.append(item)
            except Exception as e:
                logger.debug(f"解析新闻条目失败: {e}")

        return items

    def _parse_news_element(
        self,
        element,
        site_name: str,
        base_url: str,
        cutoff_date: datetime,
    ) -> RawItem | None:
        """解析单个新闻条目 HTML 元素"""
        # 标题
        title_tag = element.select_one("a, h2, h3, h4, .title, .news-title")
        if title_tag and title_tag.name == "a":
            title = title_tag.get_text(strip=True)
            url = urljoin(base_url, title_tag.get("href", ""))
        elif title_tag:
            title = title_tag.get_text(strip=True)
            link = element.select_one("a")
            url = urljoin(base_url, link.get("href", "")) if link else base_url
        else:
            # 尝试从纯文本提取
            text = element.get_text(strip=True)
            if len(text) < 5:
                return None
            title = text[:100]
            url = base_url

        if not title or len(title) < 3:
            return None

        # 摘要
        summary_tag = element.select_one(".summary, .desc, p, .content, .abstract")
        summary = summary_tag.get_text(strip=True) if summary_tag else ""

        # 发布时间
        time_tag = element.select_one(".time, .date, time, .pub-date, span[class*='time'], span[class*='date']")
        time_str = time_tag.get_text(strip=True) if time_tag else ""
        publish_date = self._parse_news_time(time_str)

        # 时效性检查
        if publish_date and publish_date < cutoff_date:
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

    def _parse_news_time(self, time_str: str) -> datetime:
        """解析新闻发布时间"""
        if not time_str:
            return datetime.now()

        time_str = time_str.strip()

        for fmt in [
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d",
            "%Y年%m月%d日",
            "%m-%d",
            "%m月%d日",
        ]:
            try:
                dt = datetime.strptime(time_str, fmt)
                if dt.year == 1900:
                    dt = dt.replace(year=datetime.now().year)
                return dt
            except ValueError:
                continue

        return datetime.now()
