"""
行业新闻爬虫
===========
在多个新闻平台按关键词搜索，采集行业相关新闻。
支持今日头条、百度新闻、新浪财经等平台。
"""

from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from bs4 import BeautifulSoup
from loguru import logger

from .base import BaseCrawler
from ..models.schemas import RawItem


class NewsCrawler(BaseCrawler):
    """行业新闻关键词搜索采集器"""

    CHANNEL = "news"

    def __init__(self, settings, cache_dir: Path):
        super().__init__(settings, cache_dir)
        self.time_range_days = settings.max_news_age_days

    def crawl(
        self,
        keywords: list[str],
        sources: list[str] = None,
        time_range_days: int = None,
        max_per_keyword: int = 20,
    ) -> list[RawItem]:
        """
        按关键词搜索行业新闻。

        Args:
            keywords: 搜索关键词列表
            sources: 目标新闻平台（今日头条、腾讯新闻等）
            time_range_days: 时间范围
            max_per_keyword: 每个关键词最多获取条数

        Returns:
            RawItem 列表
        """
        if sources is None:
            sources = ["今日头条", "百度新闻", "新浪财经"]
        if time_range_days is None:
            time_range_days = self.time_range_days

        cutoff_date = datetime.now() - timedelta(days=time_range_days)
        all_items = []

        logger.info(
            f"[新闻爬虫] 开始搜索 {len(keywords)} 个关键词 "
            f"在 {len(sources)} 个平台，时间范围: {time_range_days}天"
        )

        for keyword in keywords:
            for source in sources:
                try:
                    items = self._search_keyword(
                        keyword, source, cutoff_date, max_per_keyword
                    )
                    all_items.extend(items)
                except Exception as e:
                    logger.error(f"[新闻爬虫] 搜索失败 '{keyword}' @ {source}: {e}")

        # 缓存
        if all_items:
            self.cache_raw_data(all_items, f"{self.CHANNEL}_all")

        logger.info(f"[新闻爬虫] 总计采集 {len(all_items)} 条新闻")
        return all_items

    def _search_keyword(
        self,
        keyword: str,
        source: str,
        cutoff_date: datetime,
        max_results: int,
    ) -> list[RawItem]:
        """在指定平台搜索关键词"""
        search_url = self._build_search_url(keyword, source)
        if not search_url:
            return []

        html = self.fetch(search_url)
        if not html:
            logger.warning(f"[新闻爬虫] 搜索无响应: {source} / {keyword}")
            return []

        items = self._parse_search_results(html, keyword, source, cutoff_date)
        return items[:max_results]

    def _build_search_url(self, keyword: str, source: str) -> str:
        """构建不同平台的搜索URL"""
        encoded = quote(keyword)

        search_urls = {
            "今日头条": f"https://so.toutiao.com/search?dvpf=pc&source=input&keyword={encoded}",
            "百度新闻": f"https://www.baidu.com/s?tn=news&rtt=1&bsst=1&wd={encoded}",
            "新浪财经": f"https://search.sina.com.cn/?q={encoded}&c=news",
            "腾讯新闻": f"https://news.qq.com/search?query={encoded}",
            "搜狗新闻": f"https://news.sogou.com/news?query={encoded}",
            "必应新闻": f"https://www.bing.com/news/search?q={encoded}",
        }

        return search_urls.get(source, "")

    def _parse_search_results(
        self,
        html: str,
        keyword: str,
        source: str,
        cutoff_date: datetime,
    ) -> list[RawItem]:
        """解析搜索结果页面"""
        soup = BeautifulSoup(html, "lxml")
        items = []

        # 不同平台的不同解析策略
        if "toutiao" in source or "头条" in source:
            items = self._parse_toutiao(soup, source, cutoff_date)
        elif "baidu" in source or "百度" in source:
            items = self._parse_baidu_news(soup, source, cutoff_date)
        elif "sina" in source or "新浪" in source:
            items = self._parse_sina(soup, source, cutoff_date)
        elif "sogou" in source or "搜狗" in source:
            items = self._parse_sogou_news(soup, source, cutoff_date)
        else:
            items = self._parse_generic(soup, source, cutoff_date)

        # 标记搜索关键词
        for item in items:
            item.raw_metadata["search_keyword"] = keyword

        return items

    def _parse_toutiao(
        self, soup: BeautifulSoup, source: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """解析今日头条搜索结果"""
        items = []
        # 头条搜索结果的常见选择器
        result_items = soup.select(
            ".search-result-list .result-item, "
            ".feed-card-wrapper, "
            ".article-item, "
            "div[class*='result']"
        )

        for elem in result_items:
            try:
                title_tag = elem.select_one("a[class*='title'], a[href*='article'], h3 a, a.title")
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")

                summary_tag = elem.select_one(".abstract, .desc, p, .summary")
                summary = summary_tag.get_text(strip=True) if summary_tag else ""

                time_tag = elem.select_one(".time, .date, .create-time, span[class*='time']")
                time_str = time_tag.get_text(strip=True) if time_tag else ""
                publish_date = self._parse_news_time(time_str)

                if publish_date and publish_date < cutoff_date:
                    continue

                items.append(RawItem(
                    source_channel=self.CHANNEL,
                    source_name=source,
                    title=title,
                    url=url,
                    content=summary,
                    publish_date=publish_date,
                    raw_metadata={"source": source},
                ))
            except Exception as e:
                logger.debug(f"解析头条结果失败: {e}")

        return items

    def _parse_baidu_news(
        self, soup: BeautifulSoup, source: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """解析百度新闻搜索结果"""
        items = []
        result_items = soup.select(".result, .news-item, .result-op, div[class*='result']")

        for elem in result_items:
            try:
                title_tag = elem.select_one("h3 a, .c-title a, a[class*='title']")
                if not title_tag:
                    continue

                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")

                summary_tag = elem.select_one(".c-summary, .c-abstract, .content, p")
                summary = summary_tag.get_text(strip=True) if summary_tag else ""

                time_tag = elem.select_one(".c-time, .time, .c-author")
                time_str = time_tag.get_text(strip=True) if time_tag else ""
                publish_date = self._parse_news_time(time_str)

                if publish_date and publish_date < cutoff_date:
                    continue

                items.append(RawItem(
                    source_channel=self.CHANNEL,
                    source_name=source,
                    title=title,
                    url=url,
                    content=summary,
                    publish_date=publish_date,
                    raw_metadata={"source": source},
                ))
            except Exception as e:
                logger.debug(f"解析百度新闻失败: {e}")

        return items

    def _parse_sina(
        self, soup: BeautifulSoup, source: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """解析新浪搜索"""
        items = []
        result_items = soup.select(".result-item, .box-result, .r-info, .search-result-item")

        for elem in result_items:
            try:
                title_tag = elem.select_one("h2 a, a[href*='sina']")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")
                summary_tag = elem.select_one("p, .content, .abstract")
                summary = summary_tag.get_text(strip=True) if summary_tag else ""

                time_tag = elem.select_one(".time, .date, span[class*='time']")
                time_str = time_tag.get_text(strip=True) if time_tag else ""
                publish_date = self._parse_news_time(time_str)

                if publish_date and publish_date < cutoff_date:
                    continue

                items.append(RawItem(
                    source_channel=self.CHANNEL,
                    source_name=source,
                    title=title,
                    url=url,
                    content=summary,
                    publish_date=publish_date,
                    raw_metadata={"source": source},
                ))
            except Exception as e:
                logger.debug(f"解析新浪结果失败: {e}")

        return items

    def _parse_sogou_news(
        self, soup: BeautifulSoup, source: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """解析搜狗新闻"""
        items = []
        result_items = soup.select(".news-item, .result-item, .vrwrap, .rb")

        for elem in result_items:
            try:
                title_tag = elem.select_one("h3 a, .news-title a, a[href*='http']")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")
                summary_tag = elem.select_one("p, .news-detail, .star-wiki")
                summary = summary_tag.get_text(strip=True) if summary_tag else ""

                time_tag = elem.select_one(".news-from, .time, .news-time")
                time_str = time_tag.get_text(strip=True) if time_tag else ""
                publish_date = self._parse_news_time(time_str)

                if publish_date and publish_date < cutoff_date:
                    continue

                items.append(RawItem(
                    source_channel=self.CHANNEL,
                    source_name=source,
                    title=title,
                    url=url,
                    content=summary,
                    publish_date=publish_date,
                    raw_metadata={"source": source},
                ))
            except Exception as e:
                logger.debug(f"解析搜狗新闻失败: {e}")

        return items

    def _parse_generic(
        self, soup: BeautifulSoup, source: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """通用新闻解析（尝试常见模式）"""
        items = []
        # 通用：找所有包含链接和时间的区块
        for link in soup.select("a[href*='http']"):
            try:
                title = link.get_text(strip=True)
                if len(title) < 8:
                    continue
                url = link.get("href", "")
                parent = link.parent
                if parent:
                    full_text = parent.get_text(strip=True)
                    summary = full_text[len(title):][:200]
                else:
                    summary = ""

                items.append(RawItem(
                    source_channel=self.CHANNEL,
                    source_name=source,
                    title=title,
                    url=url,
                    content=summary,
                    publish_date=datetime.now(),
                    raw_metadata={"source": source},
                ))
            except Exception:
                continue

        # 限制数量
        return items[:50]

    def _parse_news_time(self, time_str: str) -> datetime:
        """解析新闻时间"""
        if not time_str:
            return datetime.now()

        time_str = time_str.strip()

        # "X小时前"
        import re
        hours_match = re.search(r"(\d+)小时前", time_str)
        if hours_match:
            hours = int(hours_match.group(1))
            return datetime.now() - timedelta(hours=hours)

        # "X天前"
        days_match = re.search(r"(\d+)天前", time_str)
        if days_match:
            days = int(days_match.group(1))
            return datetime.now() - timedelta(days=days)

        # "X分钟前"
        mins_match = re.search(r"(\d+)分钟前", time_str)
        if mins_match:
            mins = int(mins_match.group(1))
            return datetime.now() - timedelta(minutes=mins)

        # 标准日期格式
        for fmt in [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M",
            "%Y/%m/%d",
            "%Y年%m月%d日 %H:%M",
            "%Y年%m月%d日",
            "%m月%d日 %H:%M",
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
