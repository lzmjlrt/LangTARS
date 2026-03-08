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
    INVALID = "invalid"


@dataclass
class ParsedResponse:
    """Parsed LLM response"""
    type: ResponseType
    content: str = ""
    tool_call: 'ToolCall | None' = None


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
        
        content_stripped = content.strip()
        content_upper = content_stripped.upper()
        
        # Check for DONE response
        if content_upper.startswith("DONE:"):
            return ParsedResponse(
                type=ResponseType.DONE,
                content=content_stripped[5:].strip()
            )
        
        # Check for WORKING response
        if content_upper.startswith("WORKING:"):
            return ParsedResponse(
                type=ResponseType.WORKING,
                content=content_stripped[8:].strip()
            )
        
        # Check for NEED_SKILL response
        if content_upper.startswith("NEED_SKILL:"):
            return ParsedResponse(
                type=ResponseType.NEED_SKILL,
                content=content_stripped[11:].strip()
            )
        
        # Try to parse as tool call
        tool_call = self.extract_tool_call(content)
        if tool_call:
            return ParsedResponse(
                type=ResponseType.TOOL_CALL,
                tool_call=tool_call
            )
        
        # Invalid response
        return ParsedResponse(
            type=ResponseType.INVALID,
            content=content_stripped
        )
    
    def extract_tool_call(self, content: str) -> ToolCall | None:
        """
        Extract tool call from LLM response content.
        
        Args:
            content: Raw LLM response content
            
        Returns:
            ToolCall if found, None otherwise
        """
        # First, try to parse the entire content as JSON directly
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
