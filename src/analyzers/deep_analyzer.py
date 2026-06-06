"""
AI 深度分析模块
===============
对初筛标记为"重要"的情报进行深度分析：
- 150字核心内容概括
- 对朴道的影响分析（威胁/机会/中性）
- 应对策略建议（产品/营销/销售/技术/合规/公关）
- 紧急程度评分（1-10）
"""

from typing import Optional

from loguru import logger

from .llm_client import LLMClient
from ..models.schemas import ScreeningResult, DeepAnalysis, ResponseAction


# ============================================
# Prompt 模板
# ============================================

DEEP_ANALYSIS_SYSTEM_PROMPT = """你是朴道水汇（Pudow Water）的战略顾问，拥有净水器行业10年以上经验。

## 朴道水汇背景
- **核心技术**：DPM纳滤技术（专利技术），可保留水中天然矿物质，
  出水钙镁离子含量30-50mg/L，优于RO反渗透的"纯净水"
- **主营产品**：商用直饮机系列
  - 名士K2：2000G大流量旗舰商用机
  - 名士K1：1000G商用直饮机
  - 名士S系列：中小型企业直饮机
- **主要竞品与竞争格局**：
  - 美的净水——RO反渗透技术，品牌强、渠道广、价格激进
  - 沁园——RO为主，家用市场强，商用较弱
  - 安吉尔——部分纳滤产品线，中高端定位，近期获融资
- **核心客户**：华为、阿里巴巴、腾讯、字节跳动等大型科技企业
- **差异化优势**："健康水"概念（保留矿物质）、智能物联、节能环保
- **战略重点**：商用净水器/企业直饮水市场（非家用）

## 你的任务
基于以下情报，进行深度战略分析。请站在朴道水汇的角度思考，
提供可操作的应对建议。

## 输出格式
请严格按照以下JSON格式输出（不要包含其他文字）：
{
  "ai_summary": "用不超过150字概括本条情报的核心内容。提炼最关键的信息点，删除冗余。",
  "impact_analysis": "分析这条情报对朴道水汇的具体影响。需要说明：影响的是什么（产品/市场/技术/品牌/渠道），影响的程度（重大/一般/轻微），影响的时效（立即/短期/长期）。",
  "impact_type": "威胁",
  "our_response": [
    {"dimension": "产品策略", "action": "立即启动名士K3立项，目标3000G流量，对标美的智净3.0"},
    {"dimension": "营销策略", "action": "制作对比宣传材料，强调'大流量≠健康水'，突出朴道保留矿物质的优势"},
    {"dimension": "销售策略", "action": "针对美的目标客户（500人以上大型企业），准备差异化方案PPT"}
  ],
  "urgency_score": 8,
  "related_pudow_products": ["名士K2"]
}

## 字段说明
- **ai_summary**: ≤150字，涵盖5W1H（谁、什么事、何时、何地、为什么重要）
- **impact_analysis**: ≤200字，从朴道视角分析影响
- **impact_type**: "威胁"（对朴道不利）、"机会"（对朴道有利）、"中性"（需要关注但影响不确定）
- **our_response**: 维度可取"产品策略/营销策略/销售策略/技术研发/合规动作/公关动作"，每个维度最多3条建议
- **urgency_score**: 1-10分
  - 1-3: 可以慢慢处理的低优先级事项
  - 4-6: 需要在未来1-2周内关注
  - 7-8: 需要立即行动，影响重大
  - 9-10: 极度紧急，可能改变竞争格局
- **related_pudow_products**: 受影响的朴道产品

## 分析框架
对于竞品动态：
→ 分析竞品动作背后的战略意图
→ 对比朴道的优劣势
→ 提出具体的竞争应对

对于行业政策：
→ 分析合规要求和时间窗口
→ 提出具体的合规动作
→ 分析对竞争格局的影响

对于行业动态：
→ 分析趋势对朴道的机遇/风险
→ 提出具体行动建议

对于技术突破：
→ 分析技术对竞争格局的潜在影响
→ 评估朴道是否需要跟进或差异化
→ 提出技术路线建议
"""


class DeepAnalyzer:
    """情报深度分析器：基于 LLM 进行战略级影响分析和应对建议"""

    def __init__(self, llm_client: LLMClient, company_context: dict):
        """
        Args:
            llm_client: LLM 客户端
            company_context: 朴道公司背景信息
        """
        self.llm = llm_client
        self.company_context = company_context

    def analyze(self, screening_results: list[ScreeningResult]) -> list[DeepAnalysis]:
        """
        对重要情报进行深度分析。

        Args:
            screening_results: 初筛结果（应已过滤为 is_important=True 的条目）

        Returns:
            深度分析结果列表（按 urgency_score 降序排列）
        """
        important = [r for r in screening_results if r.is_important]
        if not important:
            logger.info("深度分析：无重要情报需要分析")
            return []

        logger.info(f"深度分析开始: {len(important)} 条重要情报")

        results = []
        for i, screening in enumerate(important, 1):
            try:
                analysis = self._analyze_single(screening, i, len(important))
                if analysis:
                    results.append(analysis)
            except Exception as e:
                logger.error(f"深度分析失败 [{i}]: {e}")
                # 兜底分析
                results.append(self._fallback_analyze(screening, str(e)))

        # 按紧急程度降序排列
        results.sort(key=lambda x: x.urgency_score, reverse=True)

        high_urgency = [r for r in results if r.urgency_score >= 7]
        logger.info(
            f"深度分析完成: {len(results)}条 → "
            f"高紧急度(≥7分): {len(high_urgency)}条"
        )

        return results

    def _analyze_single(
        self, screening: ScreeningResult, index: int, total: int
    ) -> Optional[DeepAnalysis]:
        """对单条重要情报进行深度分析"""
        item = screening.item
        raw = item.raw

        user_message = f"""请对以下{ screening.category }情报进行深度战略分析：

---
**标题**：{raw.title}
**来源**：{raw.source_name}（{raw.source_channel}）
**发布时间**：{raw.publish_date}
**初筛分类**：{screening.category} | 优先级：{screening.priority}
**初筛理由**：{screening.reason}
**关键实体**：{', '.join(screening.key_entities) if screening.key_entities else '无'}
**内容**：
{raw.content[:2000]}
---

请站在朴道水汇的战略视角，按照系统提示中的JSON格式输出分析结果。
重点关注：这对朴道的DPM纳滤技术路线、商用净水器市场、重点客户关系有何影响？"""

        logger.debug(f"深度分析 [{index}/{total}]: {raw.title[:60]}...")

        llm_result = self.llm.chat_json(
            user_message=user_message,
            system_prompt=DEEP_ANALYSIS_SYSTEM_PROMPT,
            temperature=0.3,
        )

        if llm_result is None:
            return self._fallback_analyze(screening, "LLM分析失败")

        # 解析应对策略
        response_actions = []
        for resp in llm_result.get("our_response", []):
            response_actions.append(ResponseAction(
                dimension=resp.get("dimension", "产品策略"),
                action=resp.get("action", ""),
            ))

        return DeepAnalysis(
            screening=screening,
            ai_summary=llm_result.get("ai_summary", ""),
            impact_analysis=llm_result.get("impact_analysis", ""),
            impact_type=llm_result.get("impact_type", "中性"),
            our_response=response_actions,
            urgency_score=llm_result.get("urgency_score", 5),
            related_pudow_products=llm_result.get("related_pudow_products", []),
            related_links=[raw.url] if raw.url else [],
            attachments=[],
        )

    def _fallback_analyze(
        self, screening: ScreeningResult, error: str
    ) -> DeepAnalysis:
        """规则兜底分析（LLM不可用时）"""
        return DeepAnalysis(
            screening=screening,
            ai_summary=f"{screening.item.raw.title[:150]}（AI分析不可用：{error}）",
            impact_analysis="无法自动分析，请人工评估影响。",
            impact_type="中性",
            our_response=[
                ResponseAction(
                    dimension="产品策略",
                    action="请人工查看本条情报并评估是否需要应对。",
                )
            ],
            urgency_score=5,
            related_pudow_products=[],
            related_links=[screening.item.raw.url] if screening.item.raw.url else [],
            attachments=[],
        )

    def generate_competitor_summaries(
        self, analyses: list[DeepAnalysis]
    ) -> dict[str, str]:
        """
        生成每个竞品的动态摘要。

        Returns:
            {竞品名: "一句话动态摘要"}
        """
        by_competitor: dict[str, list[DeepAnalysis]] = {}
        for analysis in analyses:
            comp = analysis.competitor
            if comp not in by_competitor:
                by_competitor[comp] = []
            by_competitor[comp].append(analysis)

        summaries = {}
        for comp, items in by_competitor.items():
            high_count = sum(1 for a in items if a.screening.priority == "高")
            titles = [a.title[:30] for a in items[:3]]  # 最多取3条标题
            title_str = "；".join(titles)

            if high_count > 0:
                summaries[comp] = f"本期活跃，{high_count}条高优先级动态。{title_str}"
            elif len(items) >= 3:
                summaries[comp] = f"本期有{len(items)}条动态，无重大变化。{title_str}"
            else:
                summaries[comp] = f"本期{len(items)}条动态：{title_str}"

        return summaries
