"""
数据清洗与去重模块
===================
合并三个渠道的原始数据 → 去重 → 过滤无关内容 → 输出清洗后数据
"""

import hashlib
import re
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Optional

from loguru import logger

from ..models.schemas import RawItem, CleanedItem


class DataCleaner:
    """数据清洗器：合并、去重、过滤"""

    def __init__(
        self,
        title_similarity_threshold: float = 0.8,
        max_news_age_days: int = 14,
        keyword_whitelist: list[str] | None = None,
        competitor_blacklist: list[str] | None = None,
    ):
        """
        Args:
            title_similarity_threshold: 标题相似度阈值（去重用）
            max_news_age_days: 最大新闻时效
            keyword_whitelist: 关键词白名单（必须关注的关键词）
            competitor_blacklist: 竞品黑名单（不相关品类关键词）
        """
        self.similarity_threshold = title_similarity_threshold
        self.max_age_days = max_news_age_days
        self.keyword_whitelist = keyword_whitelist or []
        self.competitor_blacklist = competitor_blacklist or [
            "冰箱", "洗衣机", "空调", "电视", "油烟机", "热水器",
            "招聘", "团建", "年会", "员工活动",
        ]

    def process(
        self,
        raw_items: list[RawItem],
        current_time: Optional[datetime] = None,
    ) -> list[CleanedItem]:
        """
        完整的数据清洗流程：合并 → 去重 → 过滤 → 清洗

        Args:
            raw_items: 来自所有渠道的原始数据
            current_time: 当前时间（用于时效检查），默认 now()

        Returns:
            清洗后的数据列表
        """
        if current_time is None:
            current_time = datetime.now()

        logger.info(f"[清洗] 原始数据: {len(raw_items)} 条")

        # 步骤1: 合并（计算哈希，标准化格式）
        merged = self._merge(raw_items)

        # 步骤2: 时效性检查
        time_filtered = self._check_timeliness(merged, current_time)
        logger.info(f"[清洗] 时效性过滤后: {len(time_filtered)} 条")

        # 步骤3: 去重
        deduped = self._deduplicate(time_filtered)
        logger.info(f"[清洗] 去重后: {len(deduped)} 条")

        # 步骤4: 过滤无关内容
        filtered = self._filter_irrelevant(deduped)
        logger.info(f"[清洗] 内容过滤后: {len(filtered)} 条")

        return filtered

    def _merge(self, raw_items: list[RawItem]) -> list[CleanedItem]:
        """合并原始数据，计算内容哈希"""
        cleaned = []
        for item in raw_items:
            # 计算内容哈希（标题+正文前200字）
            hash_text = f"{item.title}|{item.content[:200]}"
            content_hash = hashlib.md5(hash_text.encode("utf-8")).hexdigest()

            # 清理标题空白
            clean_title = re.sub(r"\s+", " ", item.title).strip()

            # 清理正文
            clean_content = self._clean_content(item.content)

            # 创建新的 RawItem（清理后）
            clean_raw = RawItem(
                source_channel=item.source_channel,
                source_name=item.source_name,
                title=clean_title,
                url=item.url,
                content=clean_content,
                publish_date=item.publish_date,
                raw_metadata=item.raw_metadata,
            )

            cleaned.append(CleanedItem(
                raw=clean_raw,
                content_hash=content_hash,
                is_duplicate=False,
            ))

        return cleaned

    def _clean_content(self, content: str) -> str:
        """清理正文内容"""
        if not content:
            return ""

        # 移除 HTML 标签
        content = re.sub(r"<[^>]+>", "", content)
        # 移除多余空白
        content = re.sub(r"\s+", " ", content)
        # 移除特殊字符
        content = content.replace("​", "").replace("\xa0", " ")
        return content.strip()

    def _check_timeliness(
        self, items: list[CleanedItem], current_time: datetime
    ) -> list[CleanedItem]:
        """时效性检查：过滤超过最大时效的旧内容"""
        cutoff = current_time - timedelta(days=self.max_age_days)
        valid = []

        for item in items:
            pub_date = item.raw.publish_date
            if pub_date is None:
                # 无日期信息的保留（可能无法解析时间）
                valid.append(item)
            elif pub_date >= cutoff:
                valid.append(item)
            else:
                # 检查是否为重大政策（政策类放宽时效）
                title = item.raw.title
                is_policy = any(
                    kw in title for kw in ["国标", "政策", "法规", "标准", "条例"]
                )
                if is_policy:
                    # 政策类放宽到30天
                    policy_cutoff = current_time - timedelta(days=30)
                    if pub_date >= policy_cutoff:
                        valid.append(item)
                        continue
                logger.debug(f"过期内容: {item.raw.title[:50]}... ({pub_date.strftime('%Y-%m-%d')})")

        return valid

    def _deduplicate(self, items: list[CleanedItem]) -> list[CleanedItem]:
        """
        基于标题相似度去重。
        对于相似度 > threshold 的条目，保留内容最长的一条。
        """
        if len(items) <= 1:
            return items

        # 按内容长度降序排列（优先保留内容最丰富的）
        sorted_items = sorted(
            items,
            key=lambda x: len(x.raw.content),
            reverse=True,
        )

        unique: list[CleanedItem] = []
        seen_hashes: set[str] = set()

        for item in sorted_items:
            # 精确哈希去重
            if item.content_hash in seen_hashes:
                continue

            # 标题相似度比对
            is_dup = False
            for existing in unique:
                similarity = self._title_similarity(item.raw.title, existing.raw.title)
                if similarity >= self.similarity_threshold:
                    is_dup = True
                    item.is_duplicate = True
                    item.duplicate_of = existing.raw.title
                    logger.debug(
                        f"去重: '{item.raw.title[:40]}' ≈ '{existing.raw.title[:40]}' "
                        f"(相似度: {similarity:.1%})"
                    )
                    break

            if not is_dup:
                unique.append(item)
                seen_hashes.add(item.content_hash)

        return unique

    def _filter_irrelevant(self, items: list[CleanedItem]) -> list[CleanedItem]:
        """过滤无关内容（纯广告、招聘、不相关品类）"""
        valid = []
        for item in items:
            title = item.raw.title
            content = item.raw.content
            full_text = f"{title} {content}"

            # 黑名单检查（非竞品品类）
            has_blacklist = any(
                kw in full_text for kw in self.competitor_blacklist
            )
            if has_blacklist:
                logger.debug(f"过滤（黑名单）: {title[:50]}")
                continue

            # 纯招聘内容过滤
            if self._is_recruitment(title, content):
                logger.debug(f"过滤（招聘）: {title[:50]}")
                continue

            # 纯广告过滤（内容过短 + 无实质信息）
            if len(full_text) < 20 and "广告" in title:
                logger.debug(f"过滤（广告）: {title[:50]}")
                continue

            valid.append(item)

        return valid

    def _is_recruitment(self, title: str, content: str) -> bool:
        """判断是否为招聘信息"""
        recruitment_keywords = [
            "招聘", "招贤纳士", "诚聘", "加入我们", "人才招聘",
            "岗位", "薪资", "五险一金", "学历要求", "工作经验",
        ]
        full_text = f"{title} {content}"
        score = sum(1 for kw in recruitment_keywords if kw in full_text)
        return score >= 2  # 包含2个以上招聘关键词则判定为招聘

    def _title_similarity(self, title1: str, title2: str) -> float:
        """
        计算两个标题的相似度。

        使用 SequenceMatcher + 额外的关键词 overlap 加权。
        """
        # 基本相似度
        base_sim = SequenceMatcher(None, title1, title2).ratio()

        # 关键词重叠加成
        words1 = set(title1)
        words2 = set(title2)
        if words1 and words2:
            jaccard = len(words1 & words2) / len(words1 | words2)
        else:
            jaccard = 0

        # 综合得分（SequenceMatcher 权重 0.6，Jaccard 权重 0.4）
        return base_sim * 0.6 + jaccard * 0.4

    @staticmethod
    def get_dedup_stats(items: list[CleanedItem]) -> dict:
        """获取去重统计信息"""
        duplicates = [i for i in items if i.is_duplicate]
        channels = {}
        for i in items:
            ch = i.raw.source_channel
            channels[ch] = channels.get(ch, 0) + 1

        return {
            "total": len(items),
            "duplicates_removed": len(duplicates),
            "unique": len(items) - len(duplicates),
            "by_channel": channels,
        }
