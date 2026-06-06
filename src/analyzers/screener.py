"""
AI 初筛模块
===========
对清洗后的数据进行初步筛选：
- 判断是否与净水器/朴道相关
- 分类（竞品动态/行业政策/行业动态/技术突破）
- 优先级评定（高/中/低）
- 提取关键实体
"""

from datetime import datetime
from typing import Optional

from loguru import logger

from .llm_client import LLMClient
from ..models.schemas import CleanedItem, ScreeningResult


# ============================================
# Prompt 模板
# ============================================

SCREENER_SYSTEM_PROMPT = """你是净水器行业的资深分析师。

## 背景
朴道水汇（Pudow）是一家主营DPM纳滤技术商用净水器的公司，核心卖点是"保留水中矿物质"，
主要竞品为美的净水（RO反渗透技术）、沁园（RO为主）、安吉尔（部分纳滤）。
朴道的重点市场是商用净水器/企业直饮水领域，主要客户包括华为、阿里巴巴等大型企业。

## 你的任务
判断给定的内容是否与净水器行业/朴道水汇相关，并进行分类和优先级评定。

## 输出格式
请严格按照以下JSON格式输出（不要包含其他文字）：
{
  "is_relevant": true,
  "category": "竞品动态",
  "priority": "高",
  "reason": "涉及朴道核心竞品美的发布新品，直接威胁朴道市场份额",
  "key_entities": ["美的净水", "智净3.0", "3000G"]
}

## 分类标准
- "竞品动态"：竞品公司（美的/沁园/安吉尔等）的新品发布、价格调整、融资、合作、市场活动
- "行业政策"：国家/行业标准、法规、政策变化（如净水器新国标、直饮水政策、水质标准）
- "行业动态"：市场报告、行业趋势、渠道变化、消费趋势
- "技术突破"：净水技术革新（纳滤/RO/超滤等）、新材料、新工艺
- "其他"：以上都不适用

## 优先级标准
- "高"：直接影响朴道竞争优势（如竞品发布对标新品、重大政策变化、涉及纳滤技术标准）
- "中"：行业趋势报告、竞品一般动态、市场数据、间接影响朴道的信息
- "低"：一般性行业新闻、不直接相关的动态

## 重要判断提示
1. 提及美的/沁园/安吉尔等竞品公司 → 优先归类为"竞品动态"
2. 涉及"纳滤""RO反渗透""直饮水""商用净水器""矿物质"等关键词 → 相关性高
3. 涉及"国标""政策""标准""法规"等关键词 → 归类为"行业政策"
4. 如果内容与净水器完全无关（如家电品牌的冰箱、空调等新闻） → is_relevant = false
5. 招聘信息、团建活动、年会等 → is_relevant = false
"""


class IntelligenceScreener:
    """情报初筛器：使用 LLM 判断相关性、分类、优先级"""

    def __init__(self, llm_client: LLMClient, company_context: dict):
        self.llm = llm_client
        self.company_context = company_context
        self._progress_callback = None  # 可选进度回调 (msg: str) -> None

    def screen(self, items: list[CleanedItem]) -> list[ScreeningResult]:
        """
        对清洗后的数据进行初筛。

        优化：先用关键词规则快速过滤明显无关项，再用 LLM 精确判断。
        """
        if not items:
            logger.warning("初筛：无数据")
            return []

        total = len(items)
        logger.info(f"初筛开始: {total} 条数据")

        # 第1遍：关键词快速预筛，分出"明显无关"和"需要AI判断"
        need_ai = []
        pre_filtered = []
        for item in items:
            if self._is_obviously_irrelevant(item):
                pre_filtered.append(ScreeningResult(
                    item=item, is_relevant=False, category="其他",
                    priority="低", reason="关键词预筛：与净水器无关", key_entities=[],
                ))
            else:
                need_ai.append(item)

        skipped = len(pre_filtered)
        if skipped > 0:
            logger.info(f"关键词预筛跳过 {skipped} 条明显无关，AI 需判断 {len(need_ai)} 条")
            self._emit_progress(f"🔍 预筛跳过{skipped}条无关，剩余{len(need_ai)}条AI判断")

        results = list(pre_filtered)

        for i, item in enumerate(need_ai, 1):
            try:
                idx_str = f"[{i}/{len(need_ai)}]"
                logger.info(f"初筛 {idx_str}: {item.raw.title[:60]}...")
                if i % 5 == 0 or i == 1:
                    self._emit_progress(f"🔍 AI初筛 {idx_str}（共{total}条，已跳过{skipped}条）")

                result = self._screen_single(item, i, len(need_ai))
                if result:
                    results.append(result)
            except Exception as e:
                logger.error(f"初筛失败 [{i}]: {e}")
                results.append(ScreeningResult(
                    item=item, is_relevant=True, category="其他",
                    priority="低", reason=f"AI分析异常: {str(e)[:50]}", key_entities=[],
                ))

        relevant = [r for r in results if r.is_relevant]
        important = [r for r in results if r.is_important]
        logger.info(f"初筛完成: {len(results)}条 → 相关{len(relevant)}条 → 重要{len(important)}条")
        return results

    def _emit_progress(self, msg: str):
        """通过回调发送进度到 SSE"""
        if self._progress_callback:
            try:
                self._progress_callback(msg)
            except Exception:
                pass

    def _is_obviously_irrelevant(self, item: CleanedItem) -> bool:
        """快速关键词预筛：标题明显不相关直接跳过"""
        title = item.raw.title
        content = item.raw.content or ""
        full = f"{title} {content}"[:300]
        water_kw = ["净水", "直饮水", "饮水", "水质", "纳滤", "RO", "反渗透", "过滤", "纯水", "矿泉水"]
        return not any(kw in full for kw in water_kw)

    def _screen_single(
        self, item: CleanedItem, index: int, total: int
    ) -> Optional[ScreeningResult]:
        """对单条数据进行 LLM 初筛"""
        raw = item.raw
        user_message = f"""分析标题：{raw.title}
来源：{raw.source_name}（{raw.source_channel}）
内容摘要：{raw.content[:1500]}
判断相关性、分类和优先级，输出JSON。"""

        llm_result = self.llm.chat_json(
            user_message=user_message,
            system_prompt=SCREENER_SYSTEM_PROMPT,
            temperature=0.2,
        )

        if llm_result is None:
            return self._fallback_screen(item)

        return ScreeningResult(
            item=item,
            is_relevant=llm_result.get("is_relevant", True),
            category=llm_result.get("category", "其他"),
            priority=llm_result.get("priority", "低"),
            reason=llm_result.get("reason", ""),
            key_entities=llm_result.get("key_entities", []),
        )

    def _fallback_screen(self, item: CleanedItem) -> ScreeningResult:
        """
        规则兜底（LLM不可用时）。
        基于关键词匹配进行简单分类。
        """
        title = item.raw.title
        content = item.raw.content
        full_text = f"{title} {content}"

        # 相关性判断：是否包含净水器相关关键词
        water_keywords = [
            "净水", "直饮水", "饮水", "水质", "纳滤", "RO", "反渗透",
            "过滤", "纯水", "矿泉水", "矿物质",
        ]
        is_relevant = any(kw in full_text for kw in water_keywords)

        if not is_relevant:
            return ScreeningResult(
                item=item, is_relevant=False, category="其他",
                priority="低", reason="与净水器无关（规则判断）", key_entities=[],
            )

        # 分类判断
        competitor_names = ["美的", "沁园", "安吉尔", "3M", "AO史密斯", "碧水源", "海尔"]
        is_competitor = any(name in full_text for name in competitor_names)

        policy_keywords = ["国标", "政策", "法规", "标准", "条例", "规定"]
        is_policy = any(kw in full_text for kw in policy_keywords)

        tech_keywords = ["技术", "专利", "纳滤", "RO膜", "反渗透膜", "过滤精度"]
        is_tech = any(kw in full_text for kw in tech_keywords)

        if is_competitor:
            category = "竞品动态"
        elif is_policy:
            category = "行业政策"
        elif is_tech:
            category = "技术突破"
        else:
            category = "行业动态"

        # 优先级判断
        high_keywords = ["发布", "新品", "降价", "融资", "国标", "政策"]
        is_high = any(kw in full_text for kw in high_keywords)

        return ScreeningResult(
            item=item,
            is_relevant=True,
            category=category,
            priority="高" if is_high else "中",
            reason=f"基于关键词规则判断（LLM不可用）",
            key_entities=[],
        )

    def filter_important(self, results: list[ScreeningResult]) -> list[ScreeningResult]:
        """过滤出需要深度分析的内容（相关 + 非低优先级）"""
        return [r for r in results if r.is_important]
