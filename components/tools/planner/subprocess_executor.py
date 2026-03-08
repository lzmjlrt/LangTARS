# Subprocess executor for planner
# Handles execution in separate processes for isolation and stop support

from __future__ import annotations

import asyncio
import os
import logging
import tempfile
from typing import Any, AsyncGenerator, TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SubprocessPlanner:
    """
    Subprocess-based planner executor for parallel command execution.
    Provides file-based communication for cross-process stop signals.
    """
    
    # Use cross-platform temp directory
    _TEMP_DIR = tempfile.gettempdir()
    # PID file path for tracking subprocess
    _PID_FILE = os.path.join(_TEMP_DIR, "langtars_planner_pid")
    # Stop file - when this is deleted, the thread will stop
    _STOP_FILE = os.path.join(_TEMP_DIR, "langtars_planner_stop")
    # User stop file - user can create this file to stop the current task
    _USER_STOP_FILE = os.path.join(_TEMP_DIR, "langtars_user_stop")
    
    # Process instance
    _process: Any = None
    
    @classmethod
    def check_user_stop_file(cls) -> bool:
        """Check if user created the stop file"""
        return os.path.exists(cls._USER_STOP_FILE)
    
    @classmethod
    def clear_user_stop_file(cls) -> None:
        """Clear the user stop file after stopping"""
        try:
            if os.path.exists(cls._USER_STOP_FILE):
                os.remove(cls._USER_STOP_FILE)
        except Exception:
            pass
    
    @classmethod
    def save_pid(cls, pid: int) -> None:
        """Save PID to file for cross-process tracking"""
        try:
            with open(cls._PID_FILE, 'w') as f:
                f.write(str(pid))
        except Exception as e:
            logger.error(f"Failed to save PID: {e}")
    
    @classmethod
    def read_pid(cls) -> int | None:
        """Read PID from file"""
        try:
            if os.path.exists(cls._PID_FILE):
                with open(cls._PID_FILE, 'r') as f:
                    return int(f.read().strip())
        except Exception:
            pass
        return None
    
    @classmethod
    def clear_pid(cls) -> None:
        """Clear PID file"""
        try:
            if os.path.exists(cls._PID_FILE):
                os.remove(cls._PID_FILE)
        except Exception:
            pass
    
    @classmethod
    def create_run_file(cls) -> None:
        """Create run file - existence means keep running"""
        try:
            with open(cls._STOP_FILE, 'w') as f:
                f.write("1")
            logger.debug(f"Created run file: {cls._STOP_FILE}")
        except Exception as e:
            logger.error(f"Failed to create run file {cls._STOP_FILE}: {e}")
    
    @classmethod
    def remove_run_file(cls) -> None:
        """Remove run file - absence means stop"""
        try:
            if os.path.exists(cls._STOP_FILE):
                os.remove(cls._STOP_FILE)
        except Exception:
            pass
    
    @classmethod
    def should_continue(cls) -> bool:
        """Check if should continue running - file exists means continue"""
        return os.path.exists(cls._STOP_FILE)
    
    @classmethod
    def is_running(cls) -> bool:
        """Check if a task is running (legacy, always returns False)"""
        return False


class TrueSubprocessPlanner:
    """
    True subprocess-based planner that runs in a separate process.
    This allows the stop command to directly kill the process.
    """
    
    _process: Any = None
    _pid: int | None = None
    _PID_FILE = "/tmp/langtars_subprocess_pid"
    
    @classmethod
    def is_running(cls) -> bool:
        """Check if a subprocess is running (using file-based PID tracking)"""
        # First check in-memory process
        if cls._process is not None and cls._process.poll() is None:
            return True
        
        # Fallback: check PID file
        try:
            if os.path.exists(cls._PID_FILE):
                with open(cls._PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                # Check if process is alive
                try:
                    os.kill(pid, 0)  # Signal 0 just checks if process exists
                    return True
                except OSError:
                    # Process doesn't exist, clean up file
                    try:
                        os.remove(cls._PID_FILE)
                    except:
                        pass
        except Exception:
            pass
        
        return False
    
    @classmethod
    async def kill_process(cls) -> bool:
        """Kill the running subprocess directly"""
        import subprocess
        
        killed = False
        
        # Try to kill using in-memory process reference
        if cls._process is not None:
            try:
                if cls._process.poll() is None:  # Still running
                    cls._process.terminate()
                    try:
                        cls._process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        cls._process.kill()
                        cls._process.wait()
                    killed = True
            except Exception:
                pass
            cls._process = None
        
        # Also try to kill using PID from file
        pid_to_kill = cls._pid
        if pid_to_kill is None:
            # Try to read from PID file
            try:
                if os.path.exists(cls._PID_FILE):
                    with open(cls._PID_FILE, 'r') as f:
                        pid_to_kill = int(f.read().strip())
            except Exception:
                pass
        
        if pid_to_kill:
            try:
                os.kill(pid_to_kill, 9)
                killed = True
            except OSError:
                pass  # Process already dead
        
        # Clean up PID file
        try:
            if os.path.exists(cls._PID_FILE):
                os.remove(cls._PID_FILE)
        except Exception:
            pass
        
        cls._pid = None
        
        # Clear run file
        try:
            if os.path.exists(SubprocessPlanner._STOP_FILE):
                os.remove(SubprocessPlanner._STOP_FILE)
        except Exception:
            pass
        
        if killed:
            logger.warning("[TrueSubprocess] Process killed")
        else:
            logger.warning("[TrueSubprocess] No process to kill")
        
        return True
    
    @classmethod
    async def execute_in_subprocess(
        cls,
        task: str,
        max_iterations: int,
        llm_model_uuid: str,
        plugin,
        helper_plugin=None,
        registry=None,
        session=None,
        query_id: int = 0,
    ) -> AsyncGenerator[str, None]:
        """
        Execute planner in a true subprocess, yielding output in real-time.
        Returns an async generator that yields output strings.
        """
        import subprocess
        import base64
        import json
        import uuid
        import fcntl
        import select
        
        # Import state manager for stop checks
        from .state import get_state_manager
        state_manager = get_state_manager()
        
        # Check if already running
        if cls.is_running():
            yield "⚠️ A task is already running. Use !tars stop to stop it first."
            return
        
        # Generate unique task ID
        task_id = str(uuid.uuid4())[:8]
        
        # Prepare arguments
        args = {
            "task": task,
            "max_iterations": max_iterations,
            "llm_model_uuid": llm_model_uuid,
            "config": plugin.get_config() if plugin else {},
            "task_id": task_id,
        }
        
        # Encode args as base64
        args_b64 = base64.b64encode(json.dumps(args).encode('utf-8')).decode('utf-8')
        
        # Get the path to the subprocess script
        script_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "components", "tools", "planner_subprocess.py"
        )
        
        logger.warning(f"[TrueSubprocess] Starting subprocess: {script_path}")
        
        try:
            # Start subprocess with stderr captured for logger output
            cls._process = subprocess.Popen(
                ["python3", script_path, args_b64],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
            )
            cls._pid = cls._process.pid
            
            # Save PID for external tracking
            try:
                with open(cls._PID_FILE, 'w') as f:
                    f.write(str(cls._pid))
            except Exception:
                pass
            
            # Create run file to indicate task is running
            SubprocessPlanner.create_run_file()
            
            yield f"🚀 Task started (ID: {task_id}, PID: {cls._pid})\n\n"
            
            # Set stdout to non-blocking
            stdout_fd = cls._process.stdout.fileno()
            fl = fcntl.fcntl(stdout_fd, fcntl.F_GETFL)
            fcntl.fcntl(stdout_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            
            # Also set stderr to non-blocking
            stderr_fd = cls._process.stderr.fileno()
            fl = fcntl.fcntl(stderr_fd, fcntl.F_GETFL)
            fcntl.fcntl(stderr_fd, fcntl.F_SETFL, fl | os.O_NONBLOCK)
            
            buffer = ""
            
            while True:
                # Check if process is still running
                if cls._process is None or cls._process.poll() is not None:
                    break
                
                # Check if we should stop
                if state_manager.is_stopped():
                    logger.warning("[TrueSubprocess] Stop requested, killing process")
                    await cls.kill_process()
                    yield "\n🛑 Task stopped by user."
                    return
                
                # Check user stop file
                if SubprocessPlanner.check_user_stop_file():
                    SubprocessPlanner.clear_user_stop_file()
                    await cls.kill_process()
                    yield "\n🛑 Task stopped by user."
                    return
                
                # Read stdout with timeout
                try:
                    ready, _, _ = select.select([stdout_fd], [], [], 0.1)
                    if ready:
                        chunk = cls._process.stdout.read(4096)
                        if chunk:
                            buffer += chunk.decode('utf-8', errors='replace')
                            # Process complete lines
                            while '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                if line.strip():
                                    yield line + "\n"
                except Exception as e:
                    logger.debug(f"[TrueSubprocess] Read stdout error: {e}")
                
                # Also check stderr for any errors
                try:
                    ready, _, _ = select.select([stderr_fd], [], [], 0)
                    if ready:
                        err_chunk = cls._process.stderr.read(4096)
                        if err_chunk:
                            err_text = err_chunk.decode('utf-8', errors='replace')
                            for line in err_text.strip().split('\n'):
                                if line.strip():
                                    logger.debug(f"[Subprocess] {line}")
                except Exception:
                    pass
                
                # Yield control to event loop
                await asyncio.sleep(0.05)
            
            # Read any remaining output
            try:
                if cls._process is not None:
                    remaining = cls._process.stdout.read()
                    if remaining:
                        text = remaining.decode('utf-8', errors='replace')
                        for line in text.strip().split('\n'):
                            if line.strip():
                                yield line + "\n"
            except Exception:
                pass
            
            # Clean up
            if cls._process is not None:
                try:
                    cls._process.stdout.close()
                    cls._process.stderr.close()
                except Exception:
                    pass
                returncode = cls._process.returncode
            else:
                returncode = -1
            
            cls._process = None
            cls._pid = None
            
            # Clean up files
            SubprocessPlanner.clear_pid()
            SubprocessPlanner.remove_run_file()
            
            if returncode == 0 or state_manager.is_stopped():
                if state_manager.is_stopped():
                    yield "\n🛑 Task stopped by user."
                else:
                    yield "\n✅ Task completed."
            else:
                yield f"\n⚠️ Task exited with code {returncode}"
        
        except Exception as e:
            import traceback
            logger.error(f"[TrueSubprocess] Error: {e}")
            yield f"\n❌ Error: {str(e)}\n{traceback.format_exc()}"
            await cls.kill_process()
