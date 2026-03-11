# Task state management for planner
# Handles task lifecycle, stop signals, and state tracking

from __future__ import annotations

import asyncio
import os
import tempfile
import logging
from dataclasses import dataclass, field
from typing import Any
from enum import Enum

logger = logging.getLogger(__name__)


class PlanStepStatus(Enum):
    """Status of a plan step"""
    PENDING = "pending"      # ⬜ 待执行
    IN_PROGRESS = "in_progress"  # 🔄 执行中
    COMPLETED = "completed"  # ✅ 已完成
    FAILED = "failed"        # ❌ 失败
    SKIPPED = "skipped"      # ⏭️ 跳过


@dataclass
class PlanStep:
    """Represents a single step in the execution plan"""
    index: int
    description: str
    status: PlanStepStatus = PlanStepStatus.PENDING
    result: str = ""
    
    def to_display(self) -> str:
        """Convert to display string with status icon"""
        icons = {
            PlanStepStatus.PENDING: "⬜",
            PlanStepStatus.IN_PROGRESS: "🔄",
            PlanStepStatus.COMPLETED: "✅",
            PlanStepStatus.FAILED: "❌",
            PlanStepStatus.SKIPPED: "⏭️",
        }
        icon = icons.get(self.status, "⬜")
        return f"{icon} {self.index}. {self.description}"


@dataclass
class OpenedResource:
    """Represents a resource opened during task execution"""
    resource_type: str  # "app", "browser", "browser_tab", "file"
    name: str  # App name, URL, or file path
    opened_at: float = field(default_factory=lambda: __import__('time').time())
    metadata: dict = field(default_factory=dict)  # Additional info like PID, tab_id, etc.


@dataclass
class TaskState:
    """Represents the state of a single task"""
    task_id: str
    description: str
    stopped: bool = False
    llm_call_count: int = 0
    invalid_response_count: int = 0
    messages: list = field(default_factory=list)
    last_llm_call_time: float = 0.0
    # Plan steps for multi-step tasks
    plan_steps: list[PlanStep] = field(default_factory=list)
    current_step_index: int = -1  # -1 means no step is being executed
    plan_generated: bool = False  # Whether a plan has been generated
    # Resource tracking for cleanup
    opened_resources: list[OpenedResource] = field(default_factory=list)
    auto_cleanup_enabled: bool = True  # Whether to auto-cleanup resources after task completion
    # Step verification tracking
    step_start_message_index: int = -1  # Message index when current step started
    step_verify_retry_counts: dict = field(default_factory=dict)  # {step_index: retry_count}


class StateManager:
    """
    Global state manager for planner tasks.
    Handles task lifecycle, stop signals, and state tracking.
    """
    
    # Singleton instance
    _instance: 'StateManager | None' = None
    
    # File paths for cross-process communication
    _TEMP_DIR = tempfile.gettempdir()
    _STOP_FILE = os.path.join(_TEMP_DIR, "langtars_planner_stop")
    _USER_STOP_FILE = os.path.join(_TEMP_DIR, "langtars_user_stop")
    _PID_FILE = os.path.join(_TEMP_DIR, "langtars_planner_pid")
    
    def __new__(cls) -> 'StateManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._current_task: TaskState | None = None
        self._stop_event: asyncio.Event | None = None
        self._current_asyncio_task: Any = None
        self._planner_process: Any = None
    
    @property
    def current_task(self) -> TaskState | None:
        """Get the current task state"""
        return self._current_task
    
    def create_task(self, task_id: str, description: str) -> TaskState:
        """Create a new task and set it as current"""
        self._current_task = TaskState(
            task_id=task_id,
            description=description
        )
        self._stop_event = asyncio.Event()
        self._clear_user_stop_file()
        return self._current_task
    
    def reset(self) -> None:
        """Reset all state for a new task"""
        self._current_task = None
        self._stop_event = asyncio.Event()
        self._current_asyncio_task = None
        self._planner_process = None
        self._clear_user_stop_file()
    
    def stop_current_task(self) -> bool:
        """Stop the current running task"""
        logger.warning("stop_current_task() called")
        
        if self._current_task:
            self._current_task.stopped = True
        
        # Signal the stop event
        if self._stop_event:
            try:
                self._stop_event.set()
                logger.warning("Stop event set")
            except Exception as e:
                logger.warning(f"Error setting stop event: {e}")
        
        # Cancel asyncio task if running
        if self._current_asyncio_task and not self._current_asyncio_task.done():
            try:
                self._current_asyncio_task.cancel()
                logger.warning("Cancelled asyncio task")
            except Exception as e:
                logger.warning(f"Error cancelling task: {e}")
        
        # Terminate subprocess if running
        if self._planner_process:
            try:
                self._planner_process.terminate()
                try:
                    self._planner_process.wait(timeout=1)
                except:
                    try:
                        self._planner_process.kill()
                    except:
                        pass
                self._planner_process = None
            except Exception as e:
                logger.debug(f"Error terminating process: {e}")
                self._planner_process = None
        
        return True
    
    def is_stopped(self) -> bool:
        """Check if the current task has been stopped"""
        # Check in-memory flag
        if self._current_task and self._current_task.stopped:
            return True
        
        # Check user stop file
        if self._check_user_stop_file():
            if self._current_task:
                self._current_task.stopped = True
            self._clear_user_stop_file()
            return True
        
        return False
    
    def set_asyncio_task(self, task: Any) -> None:
        """Set the current asyncio task for cancellation support"""
        self._current_asyncio_task = task
    
    def set_planner_process(self, process: Any) -> None:
        """Set the planner subprocess"""
        self._planner_process = process
    
    def increment_llm_call_count(self) -> int:
        """Increment and return the LLM call count"""
        if self._current_task:
            self._current_task.llm_call_count += 1
            return self._current_task.llm_call_count
        return 0
    
    def get_llm_call_count(self) -> int:
        """Get the current LLM call count"""
        if self._current_task:
            return self._current_task.llm_call_count
        return 0
    
    def increment_invalid_response_count(self) -> int:
        """Increment and return the invalid response count"""
        if self._current_task:
            self._current_task.invalid_response_count += 1
            return self._current_task.invalid_response_count
        return 0
    
    def reset_invalid_response_count(self) -> None:
        """Reset the invalid response count"""
        if self._current_task:
            self._current_task.invalid_response_count = 0
    
    def get_invalid_response_count(self) -> int:
        """Get the current invalid response count"""
        if self._current_task:
            return self._current_task.invalid_response_count
        return 0
    
    def update_last_llm_call_time(self, time: float) -> None:
        """Update the last LLM call time"""
        if self._current_task:
            self._current_task.last_llm_call_time = time
    
    def get_last_llm_call_time(self) -> float:
        """Get the last LLM call time"""
        if self._current_task:
            return self._current_task.last_llm_call_time
        return 0.0
    
    def get_task_info(self) -> dict:
        """Get current task info as dict"""
        if self._current_task:
            return {
                "task_id": self._current_task.task_id,
                "task_description": self._current_task.description,
            }
        return {}
    
    # Plan step management methods
    
    def set_plan_steps(self, steps: list[str]) -> None:
        """Set the plan steps for the current task
        
        Args:
            steps: List of step descriptions
        """
        if self._current_task:
            self._current_task.plan_steps = [
                PlanStep(index=i+1, description=step)
                for i, step in enumerate(steps)
            ]
            self._current_task.plan_generated = True
            self._current_task.current_step_index = -1
            logger.info(f"Plan set with {len(steps)} steps")
    
    def get_plan_steps(self) -> list[PlanStep]:
        """Get all plan steps"""
        if self._current_task:
            return self._current_task.plan_steps
        return []
    
    def has_plan(self) -> bool:
        """Check if a plan has been generated"""
        if self._current_task:
            return self._current_task.plan_generated and len(self._current_task.plan_steps) > 0
        return False
    
    def start_step(self, step_index: int) -> bool:
        """Mark a step as in progress
        
        Args:
            step_index: 1-based step index
            
        Returns:
            True if successful
        """
        if self._current_task and 1 <= step_index <= len(self._current_task.plan_steps):
            step = self._current_task.plan_steps[step_index - 1]
            step.status = PlanStepStatus.IN_PROGRESS
            self._current_task.current_step_index = step_index
            logger.info(f"Started step {step_index}: {step.description}")
            return True
        return False
    
    def complete_step(self, step_index: int, result: str = "") -> bool:
        """Mark a step as completed
        
        Args:
            step_index: 1-based step index
            result: Optional result message
            
        Returns:
            True if successful
        """
        if self._current_task and 1 <= step_index <= len(self._current_task.plan_steps):
            step = self._current_task.plan_steps[step_index - 1]
            step.status = PlanStepStatus.COMPLETED
            step.result = result
            logger.info(f"Completed step {step_index}: {step.description}")
            return True
        return False
    
    def fail_step(self, step_index: int, error: str = "") -> bool:
        """Mark a step as failed
        
        Args:
            step_index: 1-based step index
            error: Error message
            
        Returns:
            True if successful
        """
        if self._current_task and 1 <= step_index <= len(self._current_task.plan_steps):
            step = self._current_task.plan_steps[step_index - 1]
            step.status = PlanStepStatus.FAILED
            step.result = error
            logger.info(f"Failed step {step_index}: {step.description} - {error}")
            return True
        return False
    
    def skip_step(self, step_index: int, reason: str = "") -> bool:
        """Mark a step as skipped
        
        Args:
            step_index: 1-based step index
            reason: Reason for skipping
            
        Returns:
            True if successful
        """
        if self._current_task and 1 <= step_index <= len(self._current_task.plan_steps):
            step = self._current_task.plan_steps[step_index - 1]
            step.status = PlanStepStatus.SKIPPED
            step.result = reason
            logger.info(f"Skipped step {step_index}: {step.description} - {reason}")
            return True
        return False
    
    def get_current_step_index(self) -> int:
        """Get the current step index (1-based), -1 if no step is active"""
        if self._current_task:
            return self._current_task.current_step_index
        return -1
    
    def get_plan_display(self) -> str:
        """Get a formatted display of the plan with status icons"""
        if not self._current_task or not self._current_task.plan_steps:
            return ""
        
        lines = ["📋 执行计划:"]
        for step in self._current_task.plan_steps:
            lines.append(step.to_display())
        return "\n".join(lines)
    
    def is_plan_complete(self) -> bool:
        """Check if all steps are completed or skipped"""
        if not self._current_task or not self._current_task.plan_steps:
            return False
        
        for step in self._current_task.plan_steps:
            if step.status in (PlanStepStatus.PENDING, PlanStepStatus.IN_PROGRESS):
                return False
        return True
    
    def get_next_pending_step(self) -> int:
        """Get the index of the next pending step, -1 if none"""
        if not self._current_task:
            return -1
        
        for step in self._current_task.plan_steps:
            if step.status == PlanStepStatus.PENDING:
                return step.index
        return -1
    
    # Step verification tracking methods

    def mark_step_start_message_index(self, index: int) -> None:
        """Record the message list index when a step starts executing"""
        if self._current_task:
            self._current_task.step_start_message_index = index

    def get_step_start_message_index(self) -> int:
        """Get the message index from when the current step started"""
        if self._current_task:
            return self._current_task.step_start_message_index
        return -1

    def increment_step_verify_retry(self, step_index: int) -> int:
        """Increment and return the verification retry count for a step"""
        if self._current_task:
            counts = self._current_task.step_verify_retry_counts
            counts[step_index] = counts.get(step_index, 0) + 1
            return counts[step_index]
        return 0

    def get_step_verify_retry_count(self, step_index: int) -> int:
        """Get the verification retry count for a step"""
        if self._current_task:
            return self._current_task.step_verify_retry_counts.get(step_index, 0)
        return 0

    # Resource tracking methods
    
    def track_opened_resource(
        self,
        resource_type: str,
        name: str,
        metadata: dict | None = None
    ) -> None:
        """
        Track a resource that was opened during task execution.
        
        Args:
            resource_type: Type of resource ("app", "browser", "browser_tab", "file")
            name: Name/identifier of the resource (app name, URL, file path)
            metadata: Additional metadata (PID, tab_id, etc.)
        """
        if not self._current_task:
            return
        
        resource = OpenedResource(
            resource_type=resource_type,
            name=name,
            metadata=metadata or {}
        )
        self._current_task.opened_resources.append(resource)
        logger.info(f"Tracked opened resource: {resource_type} - {name}")
    
    def get_opened_resources(self, resource_type: str | None = None) -> list[OpenedResource]:
        """
        Get list of opened resources, optionally filtered by type.
        
        Args:
            resource_type: Optional filter by resource type
            
        Returns:
            List of opened resources
        """
        if not self._current_task:
            return []
        
        resources = self._current_task.opened_resources
        if resource_type:
            resources = [r for r in resources if r.resource_type == resource_type]
        return resources
    
    def remove_tracked_resource(self, resource_type: str, name: str) -> bool:
        """
        Remove a resource from tracking (e.g., when it's closed).
        
        Args:
            resource_type: Type of resource
            name: Name/identifier of the resource
            
        Returns:
            True if resource was found and removed
        """
        if not self._current_task:
            return False
        
        for i, resource in enumerate(self._current_task.opened_resources):
            if resource.resource_type == resource_type and resource.name == name:
                self._current_task.opened_resources.pop(i)
                logger.info(f"Removed tracked resource: {resource_type} - {name}")
                return True
        return False
    
    def clear_tracked_resources(self) -> None:
        """Clear all tracked resources"""
        if self._current_task:
            self._current_task.opened_resources.clear()
            logger.info("Cleared all tracked resources")
    
    def get_resources_for_cleanup(self) -> list[OpenedResource]:
        """
        Get resources that should be cleaned up after task completion.
        Returns resources in reverse order (LIFO - last opened, first closed).
        
        Returns:
            List of resources to clean up
        """
        if not self._current_task or not self._current_task.auto_cleanup_enabled:
            return []
        
        # Return in reverse order for proper cleanup
        return list(reversed(self._current_task.opened_resources))
    
    def set_auto_cleanup(self, enabled: bool) -> None:
        """Enable or disable auto-cleanup of resources"""
        if self._current_task:
            self._current_task.auto_cleanup_enabled = enabled
            logger.info(f"Auto-cleanup {'enabled' if enabled else 'disabled'}")
    
    def is_auto_cleanup_enabled(self) -> bool:
        """Check if auto-cleanup is enabled"""
        if self._current_task:
            return self._current_task.auto_cleanup_enabled
        return True
    
    def get_cleanup_summary(self) -> str:
        """Get a summary of resources that will be cleaned up"""
        resources = self.get_resources_for_cleanup()
        if not resources:
            return ""
        
        lines = ["🧹 待清理资源:"]
        for r in resources:
            lines.append(f"  - [{r.resource_type}] {r.name}")
        return "\n".join(lines)
    
    # File-based communication methods
    
    def _check_user_stop_file(self) -> bool:
        """Check if user created the stop file"""
        return os.path.exists(self._USER_STOP_FILE)
    
    def _clear_user_stop_file(self) -> None:
        """Clear the user stop file"""
        try:
            if os.path.exists(self._USER_STOP_FILE):
                os.remove(self._USER_STOP_FILE)
        except Exception:
            pass
    
    def create_run_file(self) -> None:
        """Create run file - existence means keep running"""
        try:
            with open(self._STOP_FILE, 'w') as f:
                f.write("1")
            logger.debug(f"Created run file: {self._STOP_FILE}")
        except Exception as e:
            logger.error(f"Failed to create run file: {e}")
    
    def remove_run_file(self) -> None:
        """Remove run file - absence means stop"""
        try:
            if os.path.exists(self._STOP_FILE):
                os.remove(self._STOP_FILE)
        except Exception:
            pass
    
    def should_continue(self) -> bool:
        """Check if should continue running - file exists means continue"""
        return os.path.exists(self._STOP_FILE)
    
    def save_pid(self, pid: int) -> None:
        """Save PID to file for cross-process tracking"""
        try:
            with open(self._PID_FILE, 'w') as f:
                f.write(str(pid))
        except Exception as e:
            logger.error(f"Failed to save PID: {e}")
    
    def read_pid(self) -> int | None:
        """Read PID from file"""
        try:
            if os.path.exists(self._PID_FILE):
                with open(self._PID_FILE, 'r') as f:
                    return int(f.read().strip())
        except Exception:
            pass
        return None
    
    def clear_pid(self) -> None:
        """Clear PID file"""
        try:
            if os.path.exists(self._PID_FILE):
                os.remove(self._PID_FILE)
        except Exception:
            pass


# Global state manager instance
_state_manager = StateManager()


def get_state_manager() -> StateManager:
    """Get the global state manager instance"""
    return _state_manager
