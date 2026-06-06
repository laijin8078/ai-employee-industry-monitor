"""
行业新闻多源聚合爬虫
====================
多 Adapter 聚合架构，去中心化新闻采集：
- Baidu News / Bing News / Sogou News / 通用搜索
- 每个源限制采集数量，防止单一平台波动影响整体
- 低结果自动补偿：扩展关键词 → 放宽时效 → 缓存兜底
- 竞品搜索拆分为多组 query，提升覆盖率
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from bs4 import BeautifulSoup
from loguru import logger

from .base import BaseCrawler
from ..models.schemas import RawItem


# ============================================
# 新闻源 Adapter 注册表
# ============================================

class NewsSourceAdapter:
    """单个新闻源的采集适配器"""

    def __init__(self, name: str, max_results: int = 10):
        self.name = name
        self.max_results = max_results

    def build_url(self, keyword: str) -> str:
        """构建搜索 URL（子类重写）"""
        raise NotImplementedError

    def parse_results(self, html: str, source_name: str, cutoff_date: datetime) -> list[RawItem]:
        """解析搜索结果（子类重写）"""
        raise NotImplementedError


class BaiduNewsAdapter(NewsSourceAdapter):
    """百度新闻搜索"""

    def __init__(self, max_results: int = 10):
        super().__init__("百度新闻", max_results)

    def build_url(self, keyword: str) -> str:
        return f"https://www.baidu.com/s?tn=news&rtt=1&bsst=1&wd={quote(keyword)}"

    def parse_results(self, html: str, source_name: str, cutoff_date: datetime) -> list[RawItem]:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for elem in soup.select(".result, .news-item, .result-op, div[class*='result']")[:self.max_results]:
            try:
                title_tag = elem.select_one("h3 a, .c-title a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")
                summary_tag = elem.select_one(".c-summary, .c-abstract, .content, p")
                summary = summary_tag.get_text(strip=True)[:200] if summary_tag else ""
                items.append(RawItem(
                    source_channel="news", source_name=source_name,
                    title=title, url=url, content=summary,
                    publish_date=datetime.now(),
                    raw_metadata={"source": source_name, "adapter": "baidu"},
                ))
            except Exception:
                continue
        return items


class BingNewsAdapter(NewsSourceAdapter):
    """Bing 新闻搜索"""

    def __init__(self, max_results: int = 10):
        super().__init__("Bing新闻", max_results)

    def build_url(self, keyword: str) -> str:
        return f"https://www.bing.com/news/search?q={quote(keyword)}&format=rss"

    def parse_results(self, html: str, source_name: str, cutoff_date: datetime) -> list[RawItem]:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for elem in soup.select(".news-card, .newsitem, article, .card-withoutlink")[:self.max_results]:
            try:
                title_tag = elem.select_one("a[class*='title'], h3 a, .title, a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")
                summary_tag = elem.select_one(".snippet, .description, p, .summary")
                summary = summary_tag.get_text(strip=True)[:200] if summary_tag else ""
                items.append(RawItem(
                    source_channel="news", source_name=source_name,
                    title=title, url=url, content=summary,
                    publish_date=datetime.now(),
                    raw_metadata={"source": source_name, "adapter": "bing"},
                ))
            except Exception:
                continue
        return items


class SogouNewsAdapter(NewsSourceAdapter):
    """搜狗新闻搜索"""

    def __init__(self, max_results: int = 10):
        super().__init__("搜狗新闻", max_results)

    def build_url(self, keyword: str) -> str:
        return f"https://news.sogou.com/news?query={quote(keyword)}"

    def parse_results(self, html: str, source_name: str, cutoff_date: datetime) -> list[RawItem]:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for elem in soup.select(".news-item, .result-item, .vrwrap, .rb")[:self.max_results]:
            try:
                title_tag = elem.select_one("h3 a, .news-title a, a[href*='http']")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")
                summary_tag = elem.select_one("p, .news-detail, .star-wiki")
                summary = summary_tag.get_text(strip=True)[:200] if summary_tag else ""
                items.append(RawItem(
                    source_channel="news", source_name=source_name,
                    title=title, url=url, content=summary,
                    publish_date=datetime.now(),
                    raw_metadata={"source": source_name, "adapter": "sogou"},
                ))
            except Exception:
                continue
        return items


class ToutiaoNewsAdapter(NewsSourceAdapter):
    """今日头条搜索"""

    def __init__(self, max_results: int = 5):
        super().__init__("今日头条", max_results)

    def build_url(self, keyword: str) -> str:
        return f"https://so.toutiao.com/search?dvpf=pc&source=input&keyword={quote(keyword)}"

    def parse_results(self, html: str, source_name: str, cutoff_date: datetime) -> list[RawItem]:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for elem in soup.select(".result-item, .feed-card-wrapper, div[class*='result']")[:self.max_results]:
            try:
                title_tag = elem.select_one("a[class*='title'], a[href*='article'], h3 a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")
                summary_tag = elem.select_one(".abstract, .desc, p")
                summary = summary_tag.get_text(strip=True)[:200] if summary_tag else ""
                items.append(RawItem(
                    source_channel="news", source_name=source_name,
                    title=title, url=url, content=summary,
                    publish_date=datetime.now(),
                    raw_metadata={"source": source_name, "adapter": "toutiao"},
                ))
            except Exception:
                continue
        return items


class WechatSearchAdapter(NewsSourceAdapter):
    """微信公众号文章搜索（搜索引擎检索 mp.weixin.qq.com）"""

    def __init__(self, max_results: int = 10):
        super().__init__("微信搜索", max_results)

    def build_url(self, keyword: str) -> str:
        # 百度搜索微信公众号文章
        return f"https://www.baidu.com/s?wd={quote(keyword)}+site:mp.weixin.qq.com"

    def parse_results(self, html: str, source_name: str, cutoff_date: datetime) -> list[RawItem]:
        soup = BeautifulSoup(html, "lxml")
        items = []
        for elem in soup.select(".result, .c-container")[:self.max_results]:
            try:
                title_tag = elem.select_one("h3 a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                url = title_tag.get("href", "")
                summary_tag = elem.select_one(".c-abstract, .c-span-last, .content")
                summary = summary_tag.get_text(strip=True)[:200] if summary_tag else ""
                items.append(RawItem(
                    source_channel="news", source_name=source_name,
                    title=title, url=url, content=summary,
                    publish_date=datetime.now(),
                    raw_metadata={"source": source_name, "adapter": "wechat_search"},
                ))
            except Exception:
                continue
        return items


# ============================================
# 多源聚合采集器
# ============================================

# 适配器元数据（标记是否需要快速路径/降级模式）
ADAPTER_META = {
    "百度新闻": {"priority": "normal", "cooldown_sec": 600},
    "Bing新闻": {"priority": "normal", "cooldown_sec": 600},
    "搜狗新闻": {"priority": "normal", "cooldown_sec": 900},  # 搜狗反爬严格，更长冷却
    "今日头条": {"priority": "normal", "cooldown_sec": 600},
    "微信搜索": {"priority": "degraded", "cooldown_sec": 600},  # 微信只能搜引擎检索，降级模式
}

# 默认新闻源注册表
DEFAULT_NEWS_ADAPTERS: list[NewsSourceAdapter] = [
    BaiduNewsAdapter(max_results=10),
    BingNewsAdapter(max_results=10),
    SogouNewsAdapter(max_results=10),
    ToutiaoNewsAdapter(max_results=5),
    WechatSearchAdapter(max_results=10),
]


class NewsCrawler(BaseCrawler):
    """行业新闻多源聚合采集器"""

    CHANNEL = "news"

    def __init__(self, settings, cache_dir: Path):
        super().__init__(settings, cache_dir)
        self.time_range_days = settings.max_news_age_days
        self.adapters = DEFAULT_NEWS_ADAPTERS

        # 竞品多 query 配置
        competitors = settings.company_context.get("main_competitors", [])
        self.competitor_queries = self._build_competitor_queries(competitors)

    def _build_competitor_queries(self, competitors: list[str]) -> dict:
        """为每个竞品生成多个搜索 query"""
        templates = [
            "{comp} 净水 新品",
            "{comp} 净水器 发布",
            "{comp} 战略 合作",
            "{comp} 融资",
            "{comp} 招商 渠道",
            "{comp} 滤芯 技术",
            "{comp} 饮水 科技",
            "{comp} 价格 调整",
        ]
        result = {}
        for comp in competitors:
            result[comp] = [t.format(comp=comp) for t in templates]
        return result

    def crawl(
        self,
        keywords: list[str],
        sources: list[str] = None,
        time_range_days: int = None,
        max_per_keyword: int = 20,
    ) -> list[RawItem]:
        """
        多源并行聚合搜索行业新闻。

        优化：adapter 级并行 + 短延迟 + 早停 + 精简竞品 query
        """
        if time_range_days is None:
            time_range_days = self.time_range_days

        cutoff_date = datetime.now() - timedelta(days=time_range_days)
        all_items: list[RawItem] = []
        source_stats: dict[str, int] = {}

        # === 精简查询：行业关键词 + 竞品核心 query（去重）===
        all_queries = list(dict.fromkeys(keywords))  # 保留顺序去重
        for comp, queries in self.competitor_queries.items():
            # 每个竞品只取前3个最有区分度的 query
            all_queries.extend(queries[:3])

        active_adapters = [a for a in self.adapters if not self.is_source_blocked(a.name)]
        logger.info(
            f"[新闻聚合] {len(active_adapters)}个源 × {len(all_queries)}个query "
            f"(行业{len(keywords)} + 竞品{len(all_queries)-len(keywords)}) [并行模式]"
        )

        # === 第一阶段：并行采集主要 query ===
        target_results = 30  # 收集够 30 条就停
        with ThreadPoolExecutor(max_workers=min(len(active_adapters), 4)) as pool:
            # 对每个 query，并行投递到所有 adapter
            for batch_idx in range(0, len(all_queries), 4):
                batch_queries = all_queries[batch_idx:batch_idx + 4]
                futures = {}
                for q in batch_queries:
                    for adapter in active_adapters:
                        if self.is_source_blocked(adapter.name):
                            continue
                        url = adapter.build_url(q)
                        futures[pool.submit(
                            self._fetch_and_parse, adapter, url, cutoff_date
                        )] = (adapter.name, q)

                for future in as_completed(futures):
                    adapter_name, query = futures[future]
                    try:
                        items = future.result(timeout=15)
                        if items:
                            all_items.extend(items)
                            source_stats[adapter_name] = source_stats.get(adapter_name, 0) + len(items)
                    except Exception:
                        pass

                # 早停：已有足够结果就跳出
                if len(all_items) >= target_results:
                    logger.info(f"[新闻聚合] 已达目标({target_results}条)，提前结束采集")
                    break

        # === 补偿：并行扩展关键词 ===
        if len(all_items) < 10:
            logger.warning(f"[新闻聚合] 结果偏少({len(all_items)}条)，并行补偿...")
            extra_queries = ["净水器", "直饮水机", "商用净水", "饮水设备", "净水行业"]
            with ThreadPoolExecutor(max_workers=min(len(active_adapters), 3)) as pool:
                futures = {}
                for kw in extra_queries[:4]:
                    for adapter in active_adapters[:3]:
                        if self.is_source_blocked(adapter.name):
                            continue
                        url = adapter.build_url(kw)
                        futures[pool.submit(
                            self._fetch_and_parse, adapter, url, cutoff_date
                        )] = (adapter.name, kw)
                for future in as_completed(futures):
                    try:
                        items = future.result(timeout=15)
                        if items:
                            all_items.extend(items)
                            source_stats[futures[future][0]] = source_stats.get(futures[future][0], 0) + len(items)
                    except Exception:
                        pass

        # === 兜底：加载缓存 ===
        if len(all_items) < 10:
            logger.info("[新闻聚合] 加载近7天缓存兜底")
            cached = self.load_cached_data_recent("news_all", max_age_days=7)
            if cached:
                all_items.extend(cached)

        # 去重
        unique = self._dedup_by_title(all_items)

        # 记录来源健康
        for adapter in self.adapters:
            count = source_stats.get(adapter.name, 0)
            meta = ADAPTER_META.get(adapter.name, {})
            if self.is_source_blocked(adapter.name):
                existing = self.source_health.get(adapter.name, {})
                self.record_source_health(adapter.name, "blocked",
                    count, error=existing.get("error", "反爬拦截"), fallback_used=False)
            elif count > 0:
                self.record_source_health(adapter.name, "ok", count)
            elif meta.get("priority") == "degraded":
                self.record_source_health(adapter.name, "degraded", 0,
                    error="降级源无结果", fallback_used=False)
            else:
                self.record_source_health(adapter.name, "empty", 0)

        blocked_names = [a.name for a in self.adapters if self.is_source_blocked(a.name)]
        if blocked_names:
            logger.info(f"[新闻聚合] 反爬屏蔽源: {', '.join(blocked_names)}（已跳过）")

        for adapter in self.adapters:
            count = source_stats.get(adapter.name, 0)
            tag = ""
            if self.is_source_blocked(adapter.name):
                tag = " 🛡️"
            elif ADAPTER_META.get(adapter.name, {}).get("priority") == "degraded" and count == 0:
                tag = " ⚠降级"
            logger.info(f"   [{adapter.name}] {count} 条{tag}")

        if unique:
            self.cache_raw_data(unique, "news_all")

        logger.info(f"[新闻聚合] 总计: {len(all_items)}条原始 → {len(unique)}条去重后")
        return unique

    def _fetch_and_parse(
        self, adapter: NewsSourceAdapter, url: str, cutoff_date: datetime
    ) -> list[RawItem]:
        """单个 adapter 的请求+解析（供并行调用）。每个请求前检查取消信号。"""
        if self.cancel_check and self.cancel_check():
            return []
        html = self.fetch_fast(url, source_name=adapter.name)
        if html:
            return adapter.parse_results(html, adapter.name, cutoff_date)
        return []

    def _dedup_by_title(self, items: list[RawItem]) -> list[RawItem]:
        """基于标题前缀相似度快速去重"""
        from difflib import SequenceMatcher
        seen = []
        for item in items:
            is_dup = False
            for s in seen:
                if SequenceMatcher(None, item.title[:40], s.title[:40]).ratio() > 0.85:
                    is_dup = True
                    break
            if not is_dup:
                seen.append(item)
        return seen
