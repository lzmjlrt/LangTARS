# Persistent memory module - Cross-task knowledge accumulation
# Saves task summaries and retrieves relevant memories for future tasks
# Memories are stored per user_id for multi-user isolation

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass, field, asdict

logger = logging.getLogger(__name__)

MAX_ENTRIES = 50
DEFAULT_MAX_RELEVANT = 5


@dataclass
class MemoryEntry:
    """A single task memory record"""
    task_description: str
    result_summary: str
    tools_used: list[str] = field(default_factory=list)
    timestamp: float = 0.0
    success: bool = True

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


class PlannerMemory:
    """
    Persistent task memory with per-user isolation.
    Stores task results and retrieves relevant history for new tasks.
    Each user_id gets its own memory store.
    """

    def __init__(self, memory_dir: str = None):
        self._memory_dir = memory_dir or os.path.join(
            tempfile.gettempdir(), "langtars_planner_memory"
        )
        # Per-user cache: {user_id: (entries, loaded)}
        self._user_cache: dict[str, tuple[list[MemoryEntry], bool]] = {}

    def _get_memory_file(self, user_id: str) -> str:
        """Get memory file path for a specific user"""
        safe_id = re.sub(r'[^\w\-]', '_', user_id)
        return os.path.join(self._memory_dir, f"memory_{safe_id}.json")

    def _load_user(self, user_id: str) -> list[MemoryEntry]:
        """Load memories for a specific user"""
        cached = self._user_cache.get(user_id)
        if cached and cached[1]:
            return cached[0]

        entries = []
        memory_file = self._get_memory_file(user_id)
        try:
            if os.path.exists(memory_file):
                with open(memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                entries_data = data.get('entries', [])
                entries = [MemoryEntry(**entry) for entry in entries_data]
                logger.info(f"已加载用户 {user_id} 的 {len(entries)} 条记忆")
        except (json.JSONDecodeError, OSError, TypeError) as e:
            logger.warning(f"加载用户 {user_id} 记忆文件失败: {e}")
            entries = []

        self._user_cache[user_id] = (entries, True)
        return entries

    def _save_user(self, user_id: str):
        """Save memories for a specific user (atomic write)"""
        cached = self._user_cache.get(user_id)
        if not cached:
            return

        entries = cached[0]
        memory_file = self._get_memory_file(user_id)
        data = {
            "version": 1,
            "user_id": user_id,
            "entries": [asdict(e) for e in entries],
        }
        tmp_path = memory_file + ".tmp"
        try:
            os.makedirs(self._memory_dir, exist_ok=True)
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, memory_file)
        except OSError as e:
            logger.warning(f"保存用户 {user_id} 记忆文件失败: {e}")
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    def save_task_memory(
        self,
        task: str,
        result: str,
        tools_used: list[str],
        success: bool = True,
        user_id: str = "default",
    ):
        """Save a task result to memory for a specific user"""
        entries = self._load_user(user_id)

        entry = MemoryEntry(
            task_description=task[:200],
            result_summary=result[:200],
            tools_used=tools_used[:10],
            success=success,
        )
        entries.append(entry)

        # Trim to max entries (keep newest)
        if len(entries) > MAX_ENTRIES:
            entries = entries[-MAX_ENTRIES:]

        self._user_cache[user_id] = (entries, True)
        self._save_user(user_id)
        logger.info(f"已保存用户 {user_id} 的任务记忆: {task[:50]}...")

    def get_relevant_memories(
        self, task: str, user_id: str = "default", max_count: int = DEFAULT_MAX_RELEVANT
    ) -> list[MemoryEntry]:
        """Find memories relevant to the given task for a specific user"""
        entries = self._load_user(user_id)
        if not entries:
            return []

        task_words = self._tokenize(task)
        if not task_words:
            return []

        scored = []
        for entry in entries:
            score = self._calculate_relevance(task_words, entry)
            if score > 0:
                scored.append((score, entry))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:max_count]]

    def format_memories_for_prompt(self, memories: list[MemoryEntry]) -> str:
        """Format memories as context for the system prompt"""
        if not memories:
            return ""

        lines = ["参考信息 - 以下是你之前完成类似任务的经验（仅供参考，不一定适用于当前任务）:"]
        for i, m in enumerate(memories, 1):
            status = "成功" if m.success else "失败"
            tools_str = ", ".join(m.tools_used[:5]) if m.tools_used else "无"
            ts = time.strftime("%Y-%m-%d", time.localtime(m.timestamp))
            lines.append(
                f"{i}. [{ts}] 任务: \"{m.task_description[:80]}\" "
                f"- {status}，使用工具: {tools_str}"
            )
        return "\n".join(lines)

    def _calculate_relevance(
        self, task_words: set[str], entry: MemoryEntry
    ) -> float:
        """Calculate relevance score using Jaccard similarity"""
        entry_words = self._tokenize(entry.task_description)
        if not entry_words:
            return 0.0
        intersection = task_words & entry_words
        union = task_words | entry_words
        return len(intersection) / len(union) if union else 0.0

    def _tokenize(self, text: str) -> set[str]:
        """Simple tokenization for Chinese and English text"""
        words = set(re.findall(r'[\u4e00-\u9fff]+|[a-zA-Z]+', text.lower()))
        expanded = set()
        for w in words:
            expanded.add(w)
            if re.match(r'[\u4e00-\u9fff]', w) and len(w) > 1:
                for i in range(len(w) - 1):
                    expanded.add(w[i:i+2])
        return expanded


# Module-level instance
_memory: PlannerMemory | None = None


def get_planner_memory(memory_dir: str = None) -> PlannerMemory:
    """Get or create the global planner memory instance"""
    global _memory
    if _memory is None or (memory_dir and _memory._memory_dir != memory_dir):
        _memory = PlannerMemory(memory_dir)
    return _memory
