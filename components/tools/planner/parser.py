# LLM response parser for planner
# Handles parsing of tool calls and response types from LLM output

from __future__ import annotations

import json
import re
import uuid
import logging
from dataclasses import dataclass
from typing import Any
from enum import Enum

logger = logging.getLogger(__name__)


class ResponseType(Enum):
    """Types of LLM responses"""
    DONE = "done"
    WORKING = "working"
    NEED_SKILL = "need_skill"
    TOOL_CALL = "tool_call"
    PLAN = "plan"           # New: Plan generation
    STEP = "step"           # New: Step start
    STEP_DONE = "step_done" # New: Step completed
    STEP_FAILED = "step_failed"  # New: Step failed
    STEP_SKIP = "step_skip"      # New: Step skipped
    INVALID = "invalid"


@dataclass
class ParsedResponse:
    """Parsed LLM response"""
    type: ResponseType
    content: str = ""
    tool_call: 'ToolCall | None' = None
    plan_steps: list[str] | None = None  # For PLAN type
    step_index: int = 0  # For STEP, STEP_DONE, STEP_FAILED, STEP_SKIP types


@dataclass
class ToolCall:
    """Represents a tool call from LLM"""
    id: str
    name: str
    arguments: dict[str, Any]
    
    @classmethod
    def create(cls, name: str, arguments: dict[str, Any]) -> 'ToolCall':
        """Create a new tool call with generated ID"""
        return cls(
            id=f"call_{uuid.uuid4().hex[:8]}",
            name=name,
            arguments=arguments
        )


class MockToolCall:
    """Mock tool call object for compatibility with existing code"""
    def __init__(self, name: str, args: dict[str, Any]):
        self.id = f"call_{uuid.uuid4().hex[:8]}"
        self.function = type('obj', (object,), {'name': name, 'arguments': args})()


class ResponseParser:
    """
    Parser for LLM responses.
    Handles extraction of tool calls and response type detection.
    """
    
    def parse(self, content: str) -> ParsedResponse:
        """
        Parse LLM response content and determine its type.
        
        Args:
            content: Raw LLM response content
            
        Returns:
            ParsedResponse with type and extracted data
        """
        if not content or not content.strip():
            return ParsedResponse(type=ResponseType.INVALID)
        
        # Strip <think>...</think> tags from LLM reasoning output
        content_stripped = re.sub(r'<think>.*?</think>\s*', '', content.strip(), flags=re.DOTALL).strip()
        if not content_stripped:
            return ParsedResponse(type=ResponseType.INVALID)

        content_upper = content_stripped.upper()

        # IMPORTANT: Check for tool calls FIRST (both JSON and XML format)
        # This ensures tool calls are processed even when mixed with PLAN/STEP responses
        tool_call = self.extract_tool_call(content)
        if tool_call:
            return ParsedResponse(
                type=ResponseType.TOOL_CALL,
                tool_call=tool_call
            )

        # Check for DONE response — also handle DONE: appearing after
        # a preamble line (LLM sometimes adds a short sentence before DONE:)
        if content_upper.startswith("DONE:"):
            return ParsedResponse(
                type=ResponseType.DONE,
                content=content_stripped[5:].strip()
            )
        done_match = re.search(r'^DONE:\s*', content_stripped, re.IGNORECASE | re.MULTILINE)
        if done_match:
            done_content = content_stripped[done_match.end():].strip()
            logger.debug(f"[parser] DONE: found at offset {done_match.start()}, not at start. Preamble: {content_stripped[:done_match.start()]!r}")
            return ParsedResponse(
                type=ResponseType.DONE,
                content=done_content
            )
        
        # Check for WORKING response
        if content_upper.startswith("WORKING:"):
            return ParsedResponse(
                type=ResponseType.WORKING,
                content=content_stripped[8:].strip()
            )
        working_match = re.search(r'^WORKING:\s*', content_stripped, re.IGNORECASE | re.MULTILINE)
        if working_match:
            return ParsedResponse(
                type=ResponseType.WORKING,
                content=content_stripped[working_match.end():].strip()
            )

        # Check for NEED_SKILL response
        if content_upper.startswith("NEED_SKILL:"):
            return ParsedResponse(
                type=ResponseType.NEED_SKILL,
                content=content_stripped[11:].strip()
            )
        need_skill_match = re.search(r'^NEED_SKILL:\s*', content_stripped, re.IGNORECASE | re.MULTILINE)
        if need_skill_match:
            return ParsedResponse(
                type=ResponseType.NEED_SKILL,
                content=content_stripped[need_skill_match.end():].strip()
            )
        
        # Check for PLAN response
        if content_upper.startswith("PLAN:"):
            plan_content = content_stripped[5:].strip()
            steps = self._parse_plan_steps(plan_content)
            return ParsedResponse(
                type=ResponseType.PLAN,
                content=plan_content,
                plan_steps=steps
            )
        
        # Check for STEP response (starting a step)
        step_match = re.match(r'^STEP\s+(\d+):\s*(.*)$', content_stripped, re.IGNORECASE)
        if step_match:
            step_index = int(step_match.group(1))
            step_content = step_match.group(2).strip()
            return ParsedResponse(
                type=ResponseType.STEP,
                content=step_content,
                step_index=step_index
            )
        
        # Check for STEP_DONE response
        step_done_match = re.match(r'^STEP_DONE\s+(\d+):\s*(.*)$', content_stripped, re.IGNORECASE)
        if step_done_match:
            step_index = int(step_done_match.group(1))
            step_content = step_done_match.group(2).strip()
            return ParsedResponse(
                type=ResponseType.STEP_DONE,
                content=step_content,
                step_index=step_index
            )
        
        # Check for STEP_FAILED response
        step_failed_match = re.match(r'^STEP_FAILED\s+(\d+):\s*(.*)$', content_stripped, re.IGNORECASE)
        if step_failed_match:
            step_index = int(step_failed_match.group(1))
            step_content = step_failed_match.group(2).strip()
            return ParsedResponse(
                type=ResponseType.STEP_FAILED,
                content=step_content,
                step_index=step_index
            )
        
        # Check for STEP_SKIP response
        step_skip_match = re.match(r'^STEP_SKIP\s+(\d+):\s*(.*)$', content_stripped, re.IGNORECASE)
        if step_skip_match:
            step_index = int(step_skip_match.group(1))
            step_content = step_skip_match.group(2).strip()
            return ParsedResponse(
                type=ResponseType.STEP_SKIP,
                content=step_content,
                step_index=step_index
            )
        
        # Invalid response (tool call check already done at the beginning)
        return ParsedResponse(
            type=ResponseType.INVALID,
            content=content_stripped
        )
    
    def _parse_plan_steps(self, plan_content: str) -> list[str]:
        """
        Parse plan steps from plan content.
        
        Args:
            plan_content: Content after "PLAN:"
            
        Returns:
            List of step descriptions
        """
        steps = []
        lines = plan_content.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Match numbered steps like "1. Step description" or "1) Step description"
            match = re.match(r'^(\d+)[.\)]\s*(.+)$', line)
            if match:
                step_desc = match.group(2).strip()
                if step_desc:
                    steps.append(step_desc)
            # Also match lines starting with "- " as steps
            elif line.startswith('- '):
                step_desc = line[2:].strip()
                if step_desc:
                    steps.append(step_desc)
        
        return steps
    
    def extract_tool_call(self, content: str) -> ToolCall | None:
        """
        Extract tool call from LLM response content.
        Supports both JSON format and XML format (<function_calls>).
        
        Args:
            content: Raw LLM response content
            
        Returns:
            ToolCall if found, None otherwise
        """
        # First, try to extract XML format tool call (<function_calls>)
        xml_tool_call = self._extract_xml_tool_call(content)
        if xml_tool_call:
            return xml_tool_call
        
        # Then, try to parse the entire content as JSON directly
        try:
            data = json.loads(content)
            if isinstance(data, dict) and 'tool' in data and 'arguments' in data:
                return ToolCall.create(
                    name=data['tool'],
                    arguments=data['arguments']
                )
        except (json.JSONDecodeError, AttributeError):
            pass
        
        # Try to extract and parse JSON using regex that handles nested braces
        json_match = re.search(r'\{[^{}]*"tool"[^{}]*\}[,}]', content)
        if json_match:
            # Find the full JSON including nested objects
            start = content.find('{', json_match.start())
            if start != -1:
                json_str = self._extract_json_object(content, start)
                if json_str:
                    try:
                        data = json.loads(json_str)
                        if isinstance(data, dict) and 'tool' in data and 'arguments' in data:
                            return ToolCall.create(
                                name=data['tool'],
                                arguments=data['arguments']
                            )
                    except json.JSONDecodeError:
                        pass
        
        # Fallback to regex parsing
        json_pattern = r'\{["\']tool["\']:\s*["\'](\w+)["\']\s*,\s*["\']arguments["\']:\s*\{[^}]*\}'
        match = re.search(json_pattern, content)
        if match:
            try:
                start = content.find('{', match.start())
                json_str = self._extract_json_object(content, start)
                if json_str:
                    data = json.loads(json_str)
                    tool = data.get('tool', '')
                    arguments = data.get('arguments', {})
                    if tool and isinstance(arguments, dict):
                        return ToolCall.create(name=tool, arguments=arguments)
            except (json.JSONDecodeError, KeyError):
                pass
        
        return None
    
    def _extract_xml_tool_call(self, content: str) -> ToolCall | None:
        """
        Extract tool call from XML format.
        
        Supports multiple formats:
        
        Format 1 (<function_calls>):
        <function_calls>
        <invoke name="tool_name">
        <parameter name="param1">value1</parameter>
        </invoke>
        </function_calls>
        
        Format 2 (<tool_calling>):
        <tool_calling>
        <invoke>
        <tool_name>tool_name</tool_name>
        <parameters>
        <param1>value1</param1>
        </parameters>
        </invoke>
        </tool_calling>
        
        Format 3 (<tool_call> with JSON):
        <tool_call>
        {"name": "tool_name", "arguments": {...}}
        </tool_call>
        
        Args:
            content: Raw LLM response content
            
        Returns:
            ToolCall if found, None otherwise
        """
        # Check if content contains any XML tool call format
        has_function_calls = '<function_calls>' in content or '<invoke' in content
        has_tool_calling = '<tool_calling>' in content or '<tool_name>' in content
        has_tool_call = '<tool_call>' in content
        
        if not has_function_calls and not has_tool_calling and not has_tool_call:
            return None
        
        # Try Format 3 first (<tool_call> with JSON inside)
        if has_tool_call:
            tool_call = self._extract_tool_call_json_format(content)
            if tool_call:
                return tool_call
        
        # Try Format 2 (<tool_calling> with <tool_name> and <parameters>)
        if has_tool_calling:
            tool_call = self._extract_tool_calling_format(content)
            if tool_call:
                return tool_call
        
        # Try Format 1 (<function_calls> with <invoke name="...">)
        if has_function_calls:
            tool_call = self._extract_function_calls_format(content)
            if tool_call:
                return tool_call
        
        return None
    
    def _extract_function_calls_format(self, content: str) -> ToolCall | None:
        """
        Extract tool call from <function_calls> format.
        
        Format:
        <function_calls>
        <invoke name="tool_name">
        <parameter name="param1">value1</parameter>
        </invoke>
        </function_calls>
        """
        # Try to extract invoke block with name attribute
        invoke_pattern = r'<invoke\s+name=["\']([^"\']+)["\']>(.*?)</invoke>'
        invoke_match = re.search(invoke_pattern, content, re.DOTALL)
        
        if not invoke_match:
            return None
        
        tool_name = invoke_match.group(1)
        invoke_content = invoke_match.group(2)
        
        # Extract parameters
        param_pattern = r'<parameter\s+name=["\']([^"\']+)["\']>([^<]*)</parameter>'
        params = re.findall(param_pattern, invoke_content)
        
        arguments = {}
        for param_name, param_value in params:
            param_value = param_value.strip()
            try:
                arguments[param_name] = json.loads(param_value)
            except (json.JSONDecodeError, ValueError):
                arguments[param_name] = param_value
        
        logger.info(f"Extracted function_calls format: {tool_name} with args: {arguments}")
        return ToolCall.create(name=tool_name, arguments=arguments)
    
    def _extract_tool_calling_format(self, content: str) -> ToolCall | None:
        """
        Extract tool call from <tool_calling> format.
        
        Format:
        <tool_calling>
        <invoke>
        <tool_name>tool_name</tool_name>
        <parameters>
        <param1>value1</param1>
        </parameters>
        </invoke>
        </tool_calling>
        """
        # Extract tool_name
        tool_name_match = re.search(r'<tool_name>([^<]+)</tool_name>', content)
        if not tool_name_match:
            return None
        
        tool_name = tool_name_match.group(1).strip()
        
        # Extract parameters block
        params_match = re.search(r'<parameters>(.*?)</parameters>', content, re.DOTALL)
        if not params_match:
            # No parameters, return tool call with empty arguments
            logger.info(f"Extracted tool_calling format: {tool_name} with no args")
            return ToolCall.create(name=tool_name, arguments={})
        
        params_content = params_match.group(1)
        
        # Extract individual parameters (format: <param_name>value</param_name>)
        param_pattern = r'<([^/>]+)>([^<]*)</\1>'
        params = re.findall(param_pattern, params_content)
        
        arguments = {}
        for param_name, param_value in params:
            param_name = param_name.strip()
            param_value = param_value.strip()
            try:
                arguments[param_name] = json.loads(param_value)
            except (json.JSONDecodeError, ValueError):
                arguments[param_name] = param_value
        
        logger.info(f"Extracted tool_calling format: {tool_name} with args: {arguments}")
        return ToolCall.create(name=tool_name, arguments=arguments)
    
    def _extract_tool_call_json_format(self, content: str) -> ToolCall | None:
        """
        Extract tool call from <tool_call> format with JSON inside.
        
        Format:
        <tool_call>
        {"name": "tool_name", "arguments": {...}}
        </tool_call>
        
        Also supports:
        <tool_call>
        {"tool": "tool_name", "arguments": {...}}
        </tool_call>
        """
        # Extract content between <tool_call> tags
        tool_call_match = re.search(r'<tool_call>(.*?)</tool_call>', content, re.DOTALL)
        if not tool_call_match:
            return None
        
        json_content = tool_call_match.group(1).strip()
        
        try:
            data = json.loads(json_content)
            if isinstance(data, dict):
                # Support both "name" and "tool" keys
                tool_name = data.get('name') or data.get('tool')
                arguments = data.get('arguments', {})
                
                if tool_name:
                    logger.info(f"Extracted tool_call JSON format: {tool_name} with args: {arguments}")
                    return ToolCall.create(name=tool_name, arguments=arguments)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON in <tool_call>: {e}")
        
        return None
    
    def _extract_json_object(self, content: str, start: int) -> str | None:
        """
        Extract a complete JSON object from content starting at given position.
        Handles nested braces correctly.
        
        Args:
            content: Full content string
            start: Starting position of the JSON object
            
        Returns:
            Extracted JSON string or None
        """
        depth = 0
        end = start
        
        for i, c in enumerate(content[start:], start):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        
        if depth == 0 and end > start:
            return content[start:end]
        return None
    
    def extract_tool_call_as_mock(self, content: str) -> MockToolCall | None:
        """
        Extract tool call and return as MockToolCall for compatibility.
        
        Args:
            content: Raw LLM response content
            
        Returns:
            MockToolCall if found, None otherwise
        """
        tool_call = self.extract_tool_call(content)
        if tool_call:
            return MockToolCall(tool_call.name, tool_call.arguments)
        return None
    
    def is_done_response(self, content: str) -> tuple[bool, str]:
        """
        Check if content is a DONE response.
        
        Returns:
            Tuple of (is_done, result_content)
        """
        if content.strip().upper().startswith("DONE:"):
            return True, content.strip()[5:].strip()
        return False, ""
    
    def is_working_response(self, content: str) -> tuple[bool, str]:
        """
        Check if content is a WORKING response.
        
        Returns:
            Tuple of (is_working, working_message)
        """
        if content.strip().upper().startswith("WORKING:"):
            return True, content.strip()[8:].strip()
        return False, ""
    
    def is_need_skill_response(self, content: str) -> tuple[bool, str]:
        """
        Check if content is a NEED_SKILL response.
        
        Returns:
            Tuple of (needs_skill, skill_description)
        """
        if content.strip().upper().startswith("NEED_SKILL:"):
            return True, content.strip()[11:].strip()
        return False, ""
    
    def is_plan_response(self, content: str) -> tuple[bool, list[str]]:
        """
        Check if content is a PLAN response.
        
        Returns:
            Tuple of (is_plan, list of step descriptions)
        """
        if content.strip().upper().startswith("PLAN:"):
            plan_content = content.strip()[5:].strip()
            steps = self._parse_plan_steps(plan_content)
            return True, steps
        return False, []
    
    def is_step_response(self, content: str) -> tuple[bool, int, str]:
        """
        Check if content is a STEP response (starting a step).
        
        Returns:
            Tuple of (is_step, step_index, step_description)
        """
        match = re.match(r'^STEP\s+(\d+):\s*(.*)$', content.strip(), re.IGNORECASE)
        if match:
            return True, int(match.group(1)), match.group(2).strip()
        return False, 0, ""
    
    def is_step_done_response(self, content: str) -> tuple[bool, int, str]:
        """
        Check if content is a STEP_DONE response.
        
        Returns:
            Tuple of (is_step_done, step_index, result)
        """
        match = re.match(r'^STEP_DONE\s+(\d+):\s*(.*)$', content.strip(), re.IGNORECASE)
        if match:
            return True, int(match.group(1)), match.group(2).strip()
        return False, 0, ""
    
    def is_step_failed_response(self, content: str) -> tuple[bool, int, str]:
        """
        Check if content is a STEP_FAILED response.
        
        Returns:
            Tuple of (is_step_failed, step_index, error)
        """
        match = re.match(r'^STEP_FAILED\s+(\d+):\s*(.*)$', content.strip(), re.IGNORECASE)
        if match:
            return True, int(match.group(1)), match.group(2).strip()
        return False, 0, ""
    
    def is_step_skip_response(self, content: str) -> tuple[bool, int, str]:
        """
        Check if content is a STEP_SKIP response.
        
        Returns:
            Tuple of (is_step_skip, step_index, reason)
        """
        match = re.match(r'^STEP_SKIP\s+(\d+):\s*(.*)$', content.strip(), re.IGNORECASE)
        if match:
            return True, int(match.group(1)), match.group(2).strip()
        return False, 0, ""
    
    def parse_tool_arguments(self, arguments: Any) -> dict[str, Any]:
        """
        Parse tool arguments, handling both dict and string formats.
        
        Args:
            arguments: Arguments as dict or JSON string
            
        Returns:
            Parsed arguments dict
        """
        if isinstance(arguments, dict):
            return arguments
        
        if isinstance(arguments, str):
            try:
                return json.loads(arguments)
            except json.JSONDecodeError:
                return {}
        
        return {}


# Global parser instance
_parser = ResponseParser()


def get_parser() -> ResponseParser:
    """Get the global parser instance"""
    return _parser
