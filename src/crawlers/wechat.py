"""
微信公众号爬虫
=============
通过搜狗微信搜索 (weixin.sogou.com) 获取目标公众号的文章列表。
因微信反爬机制较强，本模块优先使用缓存数据，真正抓取时需配合 Playwright。
"""

import re
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

from .base import BaseCrawler
from ..models.schemas import RawItem


class WechatCrawler(BaseCrawler):
    """微信公众号文章采集器"""

    CHANNEL = "wechat"

    def __init__(self, settings, cache_dir: Path):
        super().__init__(settings, cache_dir)
        self.time_range_days = settings.max_news_age_days

    def crawl(
        self,
        accounts: list[str],
        time_range_days: int = None,
    ) -> list[RawItem]:
        """
        爬取目标公众号的文章列表。

        Args:
            accounts: 公众号名称列表，如 ["美的净水", "沁园净水器官方"]
            time_range_days: 采集最近多少天的文章，默认14天

        Returns:
            RawItem 列表
        """
        if time_range_days is None:
            time_range_days = self.time_range_days

        cutoff_date = datetime.now() - timedelta(days=time_range_days)
        all_items = []

        logger.info(f"[微信爬虫] 开始采集 {len(accounts)} 个公众号，时间范围: {time_range_days}天")

        for account_name in accounts:
            try:
                items = self._crawl_account(account_name, cutoff_date)
                all_items.extend(items)
                logger.info(f"[微信爬虫] {account_name}: 获取 {len(items)} 篇文章")

                # 如果14天无更新则标记
                if len(items) == 0:
                    logger.warning(f"[微信爬虫] {account_name}: 该公众号{time_range_days}天无更新，建议人工检查")

            except Exception as e:
                logger.error(f"[微信爬虫] {account_name} 爬取失败: {e}")
                # 尝试从缓存恢复
                cached = self.load_cached_data(f"{self.CHANNEL}_{account_name}")
                if cached:
                    logger.info(f"[微信爬虫] {account_name}: 使用缓存数据（{len(cached)}条）")
                    all_items.extend(cached)

        # 缓存本次结果
        if all_items:
            self.cache_raw_data(all_items, f"{self.CHANNEL}_all")

        return all_items

    def _crawl_account(self, account_name: str, cutoff_date: datetime) -> list[RawItem]:
        """
        爬取单个公众号的文章。

        实际实现中会通过 Playwright 模拟浏览器，
        访问 weixin.sogou.com 搜索公众号，然后获取文章列表。

        因微信需要 Cookie/验证码等，此处展示框架；
        部署时需要配置 Playwright + Cookie 持久化。
        """
        items = []

        # === 方案1: 搜狗微信搜索 (需要 Playwright) ===
        # search_url = f"https://weixin.sogou.com/weixin?type=1&query={account_name}"
        # page_content = self._fetch_with_playwright(search_url)
        # items = self._parse_sogou_results(page_content, account_name, cutoff_date)

        # === 方案2: 微信公众平台 API (如果有合作) ===
        # ...

        # === 方案3: 第三方微信数据平台 (如新榜、西瓜数据) ===
        # ...

        # === MVP 实现: 尝试搜狗搜索，失败则返回空 ===
        try:
            search_url = f"https://weixin.sogou.com/weixin?type=1&query={account_name}"
            html = self.fetch(search_url, timeout=15)

            if html:
                items = self._parse_sogou_html(html, account_name, cutoff_date)

        except Exception as e:
            logger.debug(f"搜狗搜索失败 ({account_name}): {e}")

        return items

    def _parse_sogou_html(
        self, html: str, account_name: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """
        解析搜狗微信搜索结果页面。

        搜狗微信搜索结果结构:
        <li class="news-item">
            <div class="txt-box">
                <h3><a>标题</a></h3>
                <span class="s2">发布时间</span>
                <p class="txt-info">摘要</p>
            </div>
        </li>
        """
        from bs4 import BeautifulSoup

        items = []
        soup = BeautifulSoup(html, "lxml")

        news_items = soup.select("li.news-item, .news-list li, ul.news-list2 li")
        if not news_items:
            news_items = soup.select(".txt-box")

        for item in news_items:
            try:
                # 提取标题和链接
                title_tag = item.select_one("h3 a, .tit a, a[href*='mp.weixin']")
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")

                # 提取摘要
                summary_tag = item.select_one(".txt-info, p, .s3")
                summary = summary_tag.get_text(strip=True) if summary_tag else ""

                # 提取发布时间
                time_tag = item.select_one(".s2, .time, time")
                time_str = time_tag.get_text(strip=True) if time_tag else ""
                publish_date = self._parse_wechat_time(time_str)

                # 时效性检查
                if publish_date and publish_date < cutoff_date:
                    continue

                # 尝试提取阅读数
                reads_tag = item.select_one(".read-num, .s1")
                reads = reads_tag.get_text(strip=True) if reads_tag else ""

                item_obj = RawItem(
                    source_channel=self.CHANNEL,
                    source_name=account_name,
                    title=title,
                    url=url,
                    content=summary,
                    publish_date=publish_date,
                    raw_metadata={
                        "reads": reads,
                        "account": account_name,
                    },
                )
                items.append(item_obj)

            except Exception as e:
                logger.debug(f"解析文章条目失败: {e}")
                continue

        return items

    def _parse_wechat_time(self, time_str: str) -> datetime:
        """解析微信文章时间格式"""
        if not time_str:
            return datetime.now()

        time_str = time_str.strip()

        # "今天 14:30" 格式
        if "今天" in time_str:
            t = time_str.replace("今天", "").strip()
            today = datetime.now()
            try:
                h, m = map(int, t.split(":"))
                return today.replace(hour=h, minute=m, second=0, microsecond=0)
            except ValueError:
                return today

        # "昨天" 格式
        if "昨天" in time_str:
            yesterday = datetime.now() - timedelta(days=1)
            return yesterday.replace(hour=12, minute=0, second=0, microsecond=0)

        # "3天前" 格式
        days_match = re.search(r"(\d+)天前", time_str)
        if days_match:
            days = int(days_match.group(1))
            return (datetime.now() - timedelta(days=days)).replace(
                hour=12, minute=0, second=0, microsecond=0
            )

        # "2026-06-15" 格式
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日"]:
            try:
                return datetime.strptime(time_str, fmt)
            except ValueError:
                continue

        # 回退
        return datetime.now()

    def _fetch_with_playwright(self, url: str) -> str:
        """
        使用 Playwright 获取动态渲染的页面。
        （预留接口，部署时启用）
        """
        logger.info(f"[Playwright] 正在加载: {url}")
        # from playwright.sync_api import sync_playwright
        # with sync_playwright() as p:
        #     browser = p.chromium.launch(headless=self.crawler_config.get("headless", True))
        #     page = browser.new_page()
        #     page.goto(url, wait_until="networkidle")
        #     content = page.content()
        #     browser.close()
        #     return content
        return ""
