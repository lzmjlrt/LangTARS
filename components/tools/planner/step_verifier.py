# Step verifier module - Rule-based step result verification (执行复审)
# Validates step completion claims before marking them as done

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 暗示需要工具调用的动词
TOOL_IMPLYING_VERBS_CN = [
    "打开", "搜索", "获取", "下载", "运行", "执行", "安装",
    "发送", "读取", "写入", "创建", "删除", "点击", "输入",
    "浏览", "导航", "截图", "提取",
]
TOOL_IMPLYING_VERBS_EN = [
    "open", "search", "get", "download", "run", "execute", "install",
    "send", "read", "write", "create", "delete", "click", "type",
    "browse", "navigate", "screenshot", "extract", "fetch",
]


@dataclass
class StepVerificationResult:
    """Step verification outcome"""
    is_valid: bool
    confidence: str = "high"  # "high", "medium", "low"
    issues: list[str] = field(default_factory=list)
    feedback: str = ""


class StepVerifier:
    """
    Rule-based step result verifier.
    Checks if a step was actually completed meaningfully.
    """

    def verify(
        self,
        step_description: str,
        result_content: str,
        messages_during_step: list = None,
    ) -> StepVerificationResult:
        """
        Verify a step's completion claim.

        Args:
            step_description: Original step description
            result_content: The STEP_DONE result text
            messages_during_step: Messages exchanged during step execution

        Returns:
            StepVerificationResult
        """
        issues = []
        messages_during_step = messages_during_step or []

        # Rule 1: Non-empty result check
        if not result_content or not result_content.strip():
            issues.append("步骤结果为空，请提供具体的执行结果")

        # Rule 2: Relevance check
        if result_content and step_description:
            if not self._check_relevance(step_description, result_content):
                issues.append(
                    f"步骤结果与描述（'{step_description[:40]}'）缺乏关联，"
                    "请确认是否真正完成了该步骤"
                )

        # Rule 3: Tool usage check
        if self._implies_tool_usage(step_description):
            if not self._has_tool_calls(messages_during_step):
                issues.append(
                    "该步骤描述暗示需要使用工具，但执行过程中未发现工具调用，"
                    "请使用相应工具执行该步骤"
                )

        is_valid = len(issues) == 0
        confidence = "high" if is_valid else ("low" if len(issues) > 1 else "medium")
        feedback = "\n".join(f"- {issue}" for issue in issues) if issues else ""

        if not is_valid:
            logger.warning(
                f"步骤复审未通过: {step_description[:50]} - {len(issues)} 个问题"
            )

        return StepVerificationResult(
            is_valid=is_valid,
            confidence=confidence,
            issues=issues,
            feedback=feedback,
        )

    def _check_relevance(self, description: str, result: str) -> bool:
        """Check if result has meaningful overlap with step description"""
        desc_words = self._extract_keywords(description)
        result_words = self._extract_keywords(result)
        if not desc_words:
            return True  # Can't check, assume valid
        overlap = desc_words & result_words
        return len(overlap) > 0

    def _extract_keywords(self, text: str) -> set[str]:
        """Extract meaningful keywords from text"""
        # Extract Chinese words (2+ chars) and English words (3+ chars)
        words = set()
        for match in re.findall(r'[\u4e00-\u9fff]{2,}', text):
            words.add(match)
        for match in re.findall(r'[a-zA-Z]{3,}', text.lower()):
            words.add(match)
        # Filter out common stop words
        stop_words = {
            "the", "and", "for", "that", "this", "with", "from", "are", "was",
            "已经", "完成", "成功", "已成功", "结果", "执行", "进行",
        }
        return words - stop_words

    def _implies_tool_usage(self, description: str) -> bool:
        """Check if step description implies tool usage is needed"""
        desc_lower = description.lower()
        for verb in TOOL_IMPLYING_VERBS_CN:
            if verb in desc_lower:
                return True
        for verb in TOOL_IMPLYING_VERBS_EN:
            if verb in desc_lower:
                return True
        return False

    def _has_tool_calls(self, messages: list) -> bool:
        """Check if any tool calls exist in the messages"""
        for msg in messages:
            # Check for tool role (tool result messages)
            if hasattr(msg, 'role') and msg.role == 'tool':
                return True
            # Check for tool_calls in assistant messages
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                return True
            # Check content for tool call indicators
            if hasattr(msg, 'content') and msg.content:
                content = str(msg.content)
                try:
                    data = json.loads(content)
                    if isinstance(data, dict) and ('tool' in data or 'status' in data):
                        return True
                except (json.JSONDecodeError, ValueError):
                    pass
        return False


# Module-level instance
_verifier = StepVerifier()


def get_step_verifier() -> StepVerifier:
    """Get the global step verifier instance"""
    return _verifier
