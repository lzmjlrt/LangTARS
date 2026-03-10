# Plan reviewer module - Rule-based plan validation (门下省审议)
# Validates LLM-generated plans before execution using code rules

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 中英文动作动词列表
ACTION_VERBS_CN = [
    "打开", "关闭", "搜索", "查找", "点击", "输入", "获取", "下载",
    "上传", "创建", "删除", "修改", "编辑", "复制", "移动", "运行",
    "执行", "安装", "配置", "检查", "验证", "发送", "读取", "写入",
    "启动", "停止", "连接", "断开", "提取", "分析", "生成", "转换",
    "保存", "加载", "导入", "导出", "设置", "更新", "查看", "浏览",
    "登录", "注册", "退出", "切换", "选择", "确认", "取消", "刷新",
]

ACTION_VERBS_EN = [
    "open", "close", "search", "find", "click", "type", "get", "download",
    "upload", "create", "delete", "edit", "copy", "move", "run", "execute",
    "install", "configure", "check", "verify", "send", "read", "write",
    "start", "stop", "connect", "extract", "analyze", "generate", "convert",
    "save", "load", "import", "export", "set", "update", "view", "browse",
    "login", "register", "logout", "switch", "select", "confirm", "cancel",
    "navigate", "fetch", "scroll", "wait", "screenshot",
]

MIN_STEP_LENGTH = 5
MAX_STEPS = 10
DUPLICATE_THRESHOLD = 0.8


@dataclass
class PlanReviewResult:
    """Plan validation result"""
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    feedback: str = ""


class PlanReviewer:
    """
    Rule-based plan validator.
    Checks plan quality before execution starts.
    """

    def validate(self, steps: list[str]) -> PlanReviewResult:
        """
        Validate plan steps using predefined rules.

        Args:
            steps: List of step descriptions

        Returns:
            PlanReviewResult with validation outcome
        """
        warnings = []
        errors = []

        # Rule 1: Step count check
        if len(steps) == 0:
            errors.append("计划没有包含任何步骤")
        elif len(steps) > MAX_STEPS:
            warnings.append(f"计划包含 {len(steps)} 个步骤，建议控制在 {MAX_STEPS} 步以内")

        # Rule 2: Minimum description length
        for i, step in enumerate(steps, 1):
            if len(step.strip()) < MIN_STEP_LENGTH:
                errors.append(f"步骤 {i} 描述过于简短（'{step}'），请提供更具体的描述")

        # Rule 3: Duplicate detection
        duplicates = self._find_duplicates(steps)
        for i, j in duplicates:
            errors.append(f"步骤 {i} 和步骤 {j} 内容重复")

        # Rule 4: Action verb check
        for i, step in enumerate(steps, 1):
            if not self._has_action_verb(step):
                warnings.append(f"步骤 {i}（'{step[:30]}'）缺少明确的动作动词")

        # Build result
        is_valid = len(errors) == 0
        feedback = self._build_feedback(errors, warnings) if not is_valid else ""

        result = PlanReviewResult(
            is_valid=is_valid,
            warnings=warnings,
            errors=errors,
            feedback=feedback,
        )

        if not is_valid:
            logger.warning(f"计划审查未通过: {len(errors)} 个错误, {len(warnings)} 个警告")
        elif warnings:
            logger.info(f"计划审查通过，但有 {len(warnings)} 个警告")

        return result

    def _find_duplicates(self, steps: list[str]) -> list[tuple[int, int]]:
        """Find duplicate step pairs using sequence matching"""
        duplicates = []
        for i in range(len(steps)):
            for j in range(i + 1, len(steps)):
                ratio = difflib.SequenceMatcher(
                    None, steps[i].lower(), steps[j].lower()
                ).ratio()
                if ratio > DUPLICATE_THRESHOLD:
                    duplicates.append((i + 1, j + 1))
        return duplicates

    def _has_action_verb(self, step: str) -> bool:
        """Check if step description contains an action verb in the first 20 chars"""
        prefix = step[:20].lower()
        for verb in ACTION_VERBS_CN:
            if verb in prefix:
                return True
        for verb in ACTION_VERBS_EN:
            if verb in prefix:
                return True
        return False

    def _build_feedback(self, errors: list[str], warnings: list[str]) -> str:
        """Build feedback message for LLM"""
        parts = []
        if errors:
            parts.append("错误:\n" + "\n".join(f"- {e}" for e in errors))
        if warnings:
            parts.append("警告:\n" + "\n".join(f"- {w}" for w in warnings))
        return "\n\n".join(parts)


# Module-level instance
_reviewer = PlanReviewer()


def get_plan_reviewer() -> PlanReviewer:
    """Get the global plan reviewer instance"""
    return _reviewer
