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
from urllib.parse import quote, unquote

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

            # Level 1: 有持久化 Profile 时才用 Playwright。无 Profile 的搜狗微信高概率验证码且耗时长。
            if can_use_playwright and has_profile:
                items = self._crawl_via_playwright(account_name, cutoff_date)

            # Level 1.5: 无 Profile 时先尝试轻量搜狗微信直查，请求失败再走搜索引擎补偿。
            if not items:
                items = self._crawl_via_sogou_requests(account_name, cutoff_date)

            # Level 2: Playwright 失败或无 Profile → 搜索引擎检索
            if not items:
                logger.info(f"   [{account_name}] 微信直采失败/不可用，启用搜索引擎补偿...")
                items = self._crawl_via_search_engine(account_name, cutoff_date)

            # Level 3: 缓存降级
            if not items:
                cached = self.load_cached_data(f"{self.CHANNEL}_{account_name}")
                if not cached:
                    cached = self._load_account_from_all_cache(account_name)
                if cached:
                    items = self.filter_recent_items(cached, time_range_days)
                    if items:
                        logger.info(f"   [{account_name}] 使用两周内缓存数据（{len(items)}条）")

            if items:
                all_items.extend(items)
                self.record_source_health(account_name, "ok", len(items), fallback_used=not has_profile)
                logger.info(f"[微信爬虫] {account_name}: {len(items)} 篇")
            else:
                self.record_source_health(account_name, "empty", 0, error="本期未发现新文章")
                logger.warning(f"[微信爬虫] {account_name}: 本期无数据")

        if all_items:
            self.cache_raw_data(all_items, f"{self.CHANNEL}_all")

        return all_items

    def _crawl_via_playwright(
        self, account_name: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """通过 Playwright 访问搜狗微信搜索"""
        try:
            search_url = f"https://weixin.sogou.com/weixin?type=2&query={quote(account_name)}"
            result = self.browser.fetch_html(search_url)

            if result["html"] and "请输入验证码" not in result["html"]:
                items = self._parse_sogou_html(result["html"], account_name, cutoff_date)
                if items:
                    logger.info(f"   [{account_name}] 搜狗微信 Playwright 成功: {len(items)} 篇")
                return items
            elif "请输入验证码" in result.get("html", ""):
                logger.warning(f"   [{account_name}] 触发验证码，需人工刷新 Cookie")
            else:
                logger.debug(f"   [{account_name}] Playwright 采集为空: {result.get('error', '')}")
        except Exception as e:
            logger.debug(f"   [{account_name}] Playwright 异常: {e}")

        return []

    def _crawl_via_sogou_requests(
        self, account_name: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """通过 requests 轻量访问搜狗微信搜索。"""
        try:
            search_url = (
                "https://weixin.sogou.com/weixin"
                f"?type=2&s_from=input&query={quote(account_name)}&ie=utf8"
            )
            html = self._fetch_search_quick(search_url, source_name=f"搜狗微信:{account_name}")
            if not html:
                return []
            if "请输入验证码" in html or "antispider" in html.lower():
                self.record_source_health(account_name, "blocked", 0, error="搜狗微信验证码")
                logger.warning(f"   [{account_name}] 搜狗微信触发验证码")
                return []
            items = self._parse_sogou_html(html, account_name, cutoff_date)
            if items:
                logger.info(f"   [{account_name}] 搜狗微信轻量直查成功: {len(items)} 篇")
            return items
        except Exception as e:
            logger.debug(f"   [{account_name}] 搜狗微信轻量直查失败: {e}")
            return []

    def _crawl_via_search_engine(
        self, account_name: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """
        通过搜索引擎检索微信公众号文章。
        搜 "安吉尔 site:mp.weixin.qq.com 净水"
        """
        items = []
        aliases = self._account_aliases(account_name)
        queries = []
        for alias in aliases:
            queries.extend([
                f"{alias} site:mp.weixin.qq.com",
                f"{alias} 净水 site:mp.weixin.qq.com",
                f"{alias} 公众号 文章 site:mp.weixin.qq.com",
                f"{alias} 净水 发布 site:mp.weixin.qq.com",
            ])
        queries = list(dict.fromkeys(queries))

        for query in queries[:3]:  # 控制请求量，避免触发搜索引擎风控
            try:
                url = f"https://www.baidu.com/s?wd={quote(query)}"
                html = self._fetch_search_quick(url, source_name=f"微信百度:{account_name}")
                if html:
                    parsed = self._parse_baidu_wechat_results(html, account_name, cutoff_date, aliases)
                    items.extend(parsed)
            except Exception as e:
                logger.debug(f"   百度微信检索失败: {e}")

        # Bing RSS 对微信公众号站内检索更稳定，且不依赖 JS 渲染。
        for query in queries[:3]:
            try:
                url = f"https://www.bing.com/news/search?q={quote(query)}&format=rss"
                xml = self._fetch_search_quick(url, source_name=f"微信Bing:{account_name}")
                if xml:
                    items.extend(self._parse_bing_wechat_rss(xml, account_name, cutoff_date, aliases))
            except Exception as e:
                logger.debug(f"   Bing微信检索失败: {e}")

        return self._dedup_by_title(items)

    def _fetch_search_quick(self, url: str, source_name: str = "") -> Optional[str]:
        """微信搜索补偿专用轻量请求：单次短超时，避免拖慢整轮采集"""
        try:
            resp = self.session.get(url, timeout=6)
            if resp.status_code == 403:
                self.record_source_health(source_name or url, "blocked", 0, error="HTTP 403")
                return None
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            return resp.text
        except Exception as e:
            logger.debug(f"   [{source_name or url}] 快速搜索失败: {e}")
            return None

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

                if not publish_date or publish_date < cutoff_date:
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
        self, html: str, account_name: str, cutoff_date: datetime, aliases: list[str] = None
    ) -> list[RawItem]:
        """解析百度搜索结果中的微信公众号文章"""
        aliases = aliases or self._account_aliases(account_name)
        soup = BeautifulSoup(html, "lxml")
        items = []
        for elem in soup.select(".result, .c-container")[:10]:
            try:
                title_tag = elem.select_one("h3 a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = self._normalize_search_url(title_tag.get("href", ""))
                summary_tag = elem.select_one(".c-abstract, .c-span-last, .content")
                summary = summary_tag.get_text(strip=True)[:200] if summary_tag else ""
                text_for_match = f"{title} {url} {summary}"
                is_wechat_like = "mp.weixin.qq.com" in text_for_match or "微信公众平台" in text_for_match
                if not is_wechat_like or not self._matches_account(text_for_match, aliases):
                    continue
                if self._is_pseudo_wechat_result(text_for_match):
                    continue
                publish_date = self.parse_chinese_datetime(text_for_match)
                if not publish_date or publish_date < cutoff_date:
                    continue
                if title.startswith(("http://", "https://", "mp.weixin.qq.com")) and summary:
                    title = summary[:80]
                items.append(RawItem(
                    source_channel=self.CHANNEL, source_name=account_name,
                    title=title, url=url, content=summary,
                    publish_date=publish_date,
                    raw_metadata={"account": account_name, "method": "baidu_search"},
                ))
            except Exception:
                continue
        return items

    def _parse_bing_wechat_rss(
        self, xml: str, account_name: str, cutoff_date: datetime, aliases: list[str] = None
    ) -> list[RawItem]:
        """解析 Bing News RSS 中的微信公众号检索结果"""
        aliases = aliases or self._account_aliases(account_name)
        soup = BeautifulSoup(xml, "xml")
        items = []
        for elem in soup.select("item")[:10]:
            try:
                title = elem.title.get_text(strip=True) if elem.title else ""
                link = elem.link.get_text(strip=True) if elem.link else ""
                summary = elem.description.get_text(" ", strip=True)[:300] if elem.description else ""
                published = elem.pubDate.get_text(strip=True) if elem.pubDate else ""
                publish_date = self._parse_rss_time(published)

                text_for_match = f"{title} {link} {summary}"
                if "mp.weixin.qq.com" not in text_for_match or not self._matches_account(text_for_match, aliases):
                    continue
                if not publish_date or publish_date < cutoff_date:
                    continue

                items.append(RawItem(
                    source_channel=self.CHANNEL,
                    source_name=account_name,
                    title=title,
                    url=link,
                    content=summary,
                    publish_date=publish_date,
                    raw_metadata={"account": account_name, "method": "bing_rss"},
                ))
            except Exception:
                continue
        return items

    def _account_aliases(self, account_name: str) -> list[str]:
        """生成搜索别名，提升公众号搜索召回率"""
        aliases = [account_name]
        simplified = account_name
        for suffix in ["净水器官方", "官方旗舰店", "官方", "公众号"]:
            simplified = simplified.replace(suffix, "")
        simplified = simplified.strip()
        if simplified and simplified not in aliases:
            aliases.append(simplified)

        brand_aliases = {
            "美的": ["美的净水", "美的净水器", "Midea净水"],
            "沁园": ["沁园净水", "沁园净水器", "沁园"],
            "安吉尔": ["安吉尔", "安吉尔净水", "安吉尔净水器"],
        }
        for key, values in brand_aliases.items():
            if key in account_name:
                aliases.extend(values)
        return list(dict.fromkeys(a for a in aliases if a))

    def _matches_account(self, text: str, aliases: list[str]) -> bool:
        """判断文本是否匹配账号或品牌别名"""
        normalized = re.sub(r"\s+", "", text.lower())
        for alias in aliases:
            alias_norm = re.sub(r"\s+", "", alias.lower())
            if alias_norm and alias_norm in normalized:
                return True
        return False

    def _normalize_search_url(self, url: str) -> str:
        """尽量将搜索引擎跳转链接解析为真实链接"""
        if not url:
            return ""
        return unquote(url)

    def _load_account_from_all_cache(self, account_name: str) -> list[RawItem]:
        """从微信全量缓存中按账号筛选兜底"""
        cached = self.load_cached_data_recent(f"{self.CHANNEL}_all", max_age_days=14)
        aliases = self._account_aliases(account_name)
        matched = []
        for item in cached:
            text = f"{item.source_name} {item.title} {item.content} {item.url}"
            is_wechat_like = "mp.weixin.qq.com" in text or item.raw_metadata.get("method") == "sogou"
            if is_wechat_like and (item.source_name == account_name or self._matches_account(text, aliases)):
                matched.append(item)
        return self.filter_recent_items(matched, 14)

    def _parse_rss_time(self, time_str: str) -> Optional[datetime]:
        """解析 RSS pubDate 时间"""
        if not time_str:
            return None
        try:
            from email.utils import parsedate_to_datetime
            dt = parsedate_to_datetime(time_str)
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt
        except Exception:
            return None

    def _dedup_by_title(self, items: list[RawItem]) -> list[RawItem]:
        """基于标题去重，保留首个结果"""
        seen = set()
        unique = []
        for item in items:
            key = re.sub(r"\s+", "", item.title)[:40]
            if not key or key in seen:
                continue
            seen.add(key)
            unique.append(item)
        return unique

    def _parse_wechat_time(self, time_str: str) -> Optional[datetime]:
        """解析微信文章时间格式"""
        if not time_str:
            return None
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
        return self.parse_chinese_datetime(time_str)

    def _is_pseudo_wechat_result(self, text: str) -> bool:
        """过滤公众号编辑器、导航页、采集站等伪微信结果。"""
        pseudo_keywords = [
            "135编辑器", "96编辑器", "秀米", "新榜", "西瓜数据", "微信编辑器",
            "公众号助手", "微信公众号导航", "素材", "模板",
        ]
        return any(keyword in text for keyword in pseudo_keywords)

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
