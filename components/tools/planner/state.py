# Task state management for planner
# Handles task lifecycle, stop signals, and state tracking

from __future__ import annotations

import asyncio
import os
import tempfile
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


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
