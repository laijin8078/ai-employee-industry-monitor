"""
邮件通知模块
===========
通过 SMTP 发送情报报告邮件。
支持 HTML 格式报告，可附加企业微信机器人通知。
"""

import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
from datetime import date
from typing import Optional

import requests
from loguru import logger

from ..models.schemas import IntelligenceReport


class EmailNotifier:
    """邮件通知器"""

    def __init__(self, smtp_config: dict):
        """
        Args:
            smtp_config: SMTP 配置字典
                {
                    "host": "smtp.example.com",
                    "port": 587,
                    "user": "notify@example.com",
                    "password": "xxx",
                    "from": "AI情报员工 <notify@example.com>"
                }
        """
        self.host = smtp_config.get("host", "")
        self.port = smtp_config.get("port", 587)
        self.user = smtp_config.get("user", "")
        self.password = smtp_config.get("password", "")
        from_raw = smtp_config.get("from", "AI情报员工 <notify@pudow.com>")
        # QQ邮箱要求纯地址，自动提取邮箱地址
        if "<" in from_raw and ">" in from_raw:
            display_name = from_raw[:from_raw.index("<")].strip()
            addr = from_raw[from_raw.index("<")+1:from_raw.index(">")].strip()
            self.from_addr = formataddr((display_name, addr))
        else:
            self.from_addr = from_raw

    @property
    def is_configured(self) -> bool:
        """检查 SMTP 是否已配置"""
        return bool(self.host and self.user and self.password)

    def send_report(
        self,
        report: IntelligenceReport,
        recipients: list[str],
        html_content: str,
        json_filepath: Optional[str] = None,
    ) -> bool:
        """
        发送邮件报告。

        Args:
            report: 情报报告
            recipients: 收件人列表
            html_content: HTML 邮件正文
            json_filepath: JSON 报告文件路径（可选附件）

        Returns:
            是否发送成功
        """
        if not self.is_configured:
            logger.warning("SMTP 未配置，跳过邮件发送")
            return False

        if not recipients:
            logger.warning("无收件人，跳过邮件发送")
            return False

        try:
            subject = self._build_subject(report)
            msg = self._build_message(subject, recipients, html_content, json_filepath)

            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(msg)

            logger.info(f"邮件已发送 → {len(recipients)} 个收件人: {', '.join(recipients[:3])}")
            return True

        except smtplib.SMTPAuthenticationError:
            logger.error("SMTP 认证失败，请检查用户名/密码")
            return False
        except smtplib.SMTPConnectError:
            logger.error(f"SMTP 连接失败: {self.host}:{self.port}")
            return False
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            return False

    def send_immediate_alert(self, report: IntelligenceReport, recipients: list[str]) -> bool:
        """
        发送高优先级即时告警（简化版邮件，不含完整报告）。
        当本期有高优先级情报时使用。
        """
        high_items = []
        for items in report.intelligence_by_category.values():
            for item in items:
                if item.screening.priority == "高":
                    high_items.append(item)

        if not high_items:
            return False

        subject = f"⚠ 紧急情报告警：{len(high_items)}条高优先级情报 [{report.report_date}]"
        lines = [f"朴道水汇竞品情报系统 — 高优先级告警", "", f"本期发现 {len(high_items)} 条高优先级情报：", ""]

        for i, item in enumerate(high_items, 1):
            lines.append(f"{i}. [{item.screening.category}] {item.title}")
            lines.append(f"   来源: {item.source}")
            lines.append(f"   摘要: {item.ai_summary[:100]}...")
            lines.append(f"   影响: {item.impact_analysis[:100]}...")
            lines.append("")

        lines.append(f"详情请查看完整报告（邮件附件或系统内查看）。")
        body = "\n".join(lines)

        try:
            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = Header(subject, "utf-8")
            msg["From"] = self.from_addr
            msg["To"] = ", ".join(recipients)

            with smtplib.SMTP(self.host, self.port, timeout=30) as server:
                server.ehlo()
                server.starttls()
                server.login(self.user, self.password)
                server.send_message(msg)

            logger.info(f"紧急告警已发送 → {len(recipients)} 个收件人")
            return True
        except Exception as e:
            logger.error(f"紧急告警发送失败: {e}")
            return False

    def send_wechat_bot(self, report: IntelligenceReport, webhook_url: str) -> bool:
        """
        通过企业微信机器人发送通知。

        Args:
            report: 情报报告
            webhook_url: 企业微信机器人 Webhook URL

        Returns:
            是否发送成功
        """
        if not webhook_url:
            logger.debug("企业微信 Webhook 未配置，跳过")
            return False

        high_count = sum(
            1 for items in report.intelligence_by_category.values()
            for item in items
            if item.screening.priority == "高"
        )

        markdown_content = (
            f"## 🔍 竞品情报报告 ({report.report_date})\n"
            f"**报告区间**: {report.report_period}\n"
            f"**采集总量**: {report.total_items} 条 | **重要情报**: {report.important_items} 条\n"
            f"**高优先级**: {high_count} 条\n\n"
            f"### 本期摘要\n{report.summary}\n\n"
            f"### 综合建议\n{report.recommendation[:200]}\n\n"
            f"> 请查看邮件获取完整报告 | 下次监控: {report.next_monitoring_date}"
        )

        try:
            resp = requests.post(
                webhook_url,
                json={
                    "msgtype": "markdown",
                    "markdown": {"content": markdown_content},
                },
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info("企业微信通知已发送")
                return True
            else:
                logger.warning(f"企业微信通知失败: {resp.text}")
                return False
        except Exception as e:
            logger.error(f"企业微信通知失败: {e}")
            return False

    def should_send_immediate(self, report: IntelligenceReport) -> bool:
        """判断是否需要立即发送（包含高优先级情报时）"""
        for items in report.intelligence_by_category.values():
            for item in items:
                if item.screening.priority == "高":
                    return True
        return False

    def _build_subject(self, report: IntelligenceReport) -> str:
        """构建邮件标题"""
        high_count = sum(
            1 for items in report.intelligence_by_category.values()
            for item in items
            if item.screening.priority == "高"
        )
        if high_count > 0:
            return f"⚠ 竞品情报报告 [{report.report_date}] — {high_count}条高优先级情报"
        elif report.important_items > 0:
            return f"📊 竞品情报报告 [{report.report_date}] — {report.important_items}条值得关注"
        else:
            return f"📋 竞品情报报告 [{report.report_date}] — 本期无重大动态"

    def _build_message(
        self,
        subject: str,
        recipients: list[str],
        html_content: str,
        json_filepath: Optional[str] = None,
    ) -> MIMEMultipart:
        """构建邮件消息体"""
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = self.from_addr
        msg["To"] = ", ".join(recipients)

        # HTML 正文
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        # JSON 附件（如果提供）
        if json_filepath:
            try:
                with open(json_filepath, "r", encoding="utf-8") as f:
                    json_data = f.read()
                attachment = MIMEText(json_data, "plain", "utf-8")
                attachment.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=Header(f"情报报告_{date.today()}.json", "utf-8").encode(),
                )
                msg.attach(attachment)
            except Exception as e:
                logger.warning(f"添加 JSON 附件失败: {e}")

        return msg
