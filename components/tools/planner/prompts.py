# System prompts for planner
# Contains all prompt templates used by the planner

from __future__ import annotations


class PromptManager:
    """
    Manages system prompts and message templates for the planner.
    Centralizes all prompt-related logic for easy maintenance.
    """
    
    SYSTEM_PROMPT = """You are a task planning assistant. Your job is to help users accomplish tasks on their computer by intelligently calling tools.

## Tool Calling - IMPORTANT:
When you need to execute a tool, respond with ONLY a JSON object in this exact format:
{"tool": "tool_name", "arguments": {"param1": "value1", "param2": "value2"}}

## Response Format:

When the task is COMPLETED, respond with text starting with:
DONE: Your summary here

When the task is in progress but not yet complete, respond with text starting with:
WORKING: Description of what you are currently doing

When you need a skill/capability that doesn't exist in available tools, respond with:
NEED_SKILL: Description of what capability you need

## CRITICAL: After tool execution, you MUST respond with DONE

After most tools return {"success": true}, you MUST immediately return DONE: with a summary.
- Opening an app? DONE: Opened [app name]
- Navigated to a website? DONE: Opened [URL]
- Executed a command? DONE: Command executed successfully
- DO NOT keep calling the same tool repeatedly!

EXCEPTION: After ask_user tool returns, you MUST continue executing the original task using the user's answer!
- ask_user is for getting user input to continue the task, NOT for completing the task
- After ask_user returns {"success": true, "answer": "..."}, use the answer to continue the task

## Browser Selection Rules:
- If user says "open website" or "go to website" WITHOUT specifying browser → Use browser_navigate (Playwright)
- If user says "open Safari" or "use Safari" → Use safari_* tools (controls real Safari app)
- If user says "open Chrome" or "use Chrome" → Use chrome_* tools (controls real Chrome app)
- For general web automation: use browser_navigate, browser_click, browser_type, browser_screenshot

## Important Rules:
1. ALWAYS try to use available tools before giving up
2. ALWAYS respond with valid JSON when calling tools
3. Use browser_navigate for general web automation (Playwright)
4. Use safari_* tools when user specifically mentions Safari
5. Use chrome_* tools when user specifically mentions Chrome
6. Use shell for terminal commands
7. Use fetch_url to get web page content
8. After a tool returns success:
   - If you already have the FINAL answer → respond with "DONE: Your summary"
   - If you need MORE information → respond with "WORKING: [what you're doing]" then call more tools
9. If user asks for content/summary, fetch it first THEN return DONE with the summary
10. When navigating to a search results page, you MUST either:
    - Click on a relevant result to go to the actual page, then get its content
    - Or use browser_get_content to extract information from the search results
11. Use browser_get_content to get the actual text/content from the page after any navigation or click
12. If the user's request is ambiguous, call ask_user first to clarify, then continue execution
13. CRITICAL - ask_user behavior: After ask_user returns with user's answer, you MUST continue executing the original task using that answer
14. CRITICAL - Sensitive Information: When a task requires sensitive information (passwords, API keys, etc.), use ask_user to request this information from the user
15. CRITICAL - Non-Interactive Commands: All shell/powershell commands MUST be non-interactive. Use ask_user to collect information first
16. CRITICAL - Error Handling: When a tool execution fails, analyze the error and use ask_user to request missing information. NEED_SKILL should ONLY be used when you need a completely new capability
17. CRITICAL - ask_user Options: For open-ended questions, use an empty options array. For specific choices, provide meaningful options

If no tool can accomplish the user's request, then respond with NEED_SKILL: and describe what you need.
"""

    @classmethod
    def get_system_prompt(cls) -> str:
        """Get the system prompt"""
        return cls.SYSTEM_PROMPT
    
    @classmethod
    def get_task_prompt(cls, task: str, tools_description: str = None) -> str:
        """
        Build the initial task prompt.
        
        Args:
            task: User's task description
            tools_description: (Deprecated) Description of available tools - no longer used with native tool calling
            
        Returns:
            Formatted task prompt
        """
        # With native tool calling, tools are provided via API parameters
        # No need to include tool descriptions in the prompt
        return f"""{task}

请使用可用的工具来完成这个任务。工具已通过 API 原生 tool calling 机制提供。"""

    @classmethod
    def get_tool_result_hint(cls, result: dict, task: str, truncate_length: int = 500) -> str:
        """
        Build a hint message after tool execution.
        
        Args:
            result: Tool execution result
            task: Original task description
            truncate_length: Max length for result in hint
            
        Returns:
            Formatted hint message
        """
        import json
        
        # Check if this is an ask_user tool result - user's answer needs to be processed
        if result.get("answer") is not None and result.get("question") is not None:
            user_answer = result.get("answer", "")
            question = result.get("question", "")
            return f"""用户回答了你的问题：
问题: {question}
用户回答: {user_answer}

重要：用户的回答是任务的输入，你需要根据用户的回答继续执行任务。
- 用户的原始任务是：{task}
- 请根据用户的回答决定下一步操作
- 如果需要调用工具 → 使用原生 tool calling
- 如果任务已完成 → 返回 DONE: 执行结果总结"""
        
        result_str = json.dumps(result)[:truncate_length]
        
        return f"""
工具执行结果：{result_str}

请判断任务是否已完成：
- 用户的原始任务是：{task}
- 如果已经获取到最终答案 → 返回 DONE: 答案
- 如果还需要更多步骤 → 返回 WORKING: 正在做什么
- 如果需要调用工具 → 使用原生 tool calling

关键：不要重复执行相同的工具！"""

    @classmethod
    def get_tool_result_hint_with_content(cls, result: dict, task: str, truncate_length: int = 500) -> str:
        """
        Build a hint message after tool execution, emphasizing content extraction.
        
        Args:
            result: Tool execution result
            task: Original task description
            truncate_length: Max length for result in hint
            
        Returns:
            Formatted hint message
        """
        import json
        
        # Check if this is an ask_user tool result - user's answer needs to be processed
        if result.get("answer") is not None and result.get("question") is not None:
            user_answer = result.get("answer", "")
            question = result.get("question", "")
            return f"""用户回答了你的问题：
问题: {question}
用户回答: {user_answer}

重要：用户的回答是任务的输入，你需要根据用户的回答继续执行任务。
- 用户的原始任务是：{task}
- 请根据用户的回答决定下一步操作
- 如果需要调用工具 → 使用原生 tool calling
- 如果任务已完成 → 返回 DONE: 执行结果总结"""
        
        result_str = json.dumps(result)[:truncate_length]
        
        return f"""
上一个工具执行结果：{result_str}

请判断任务是否已完成：
- 用户的原始任务是：{task}
- 如果已经获取到页面内容 → 立即返回 DONE: 总结内容
- 如果还需要更多步骤 → 返回 WORKING: 正在做什么
- 如果需要调用工具 → 使用原生 tool calling

关键：不要重复执行相同的工具！"""

    @classmethod
    def get_invalid_response_hint(cls, content: str, truncate_length: int = 200) -> str:
        """
        Build a hint message for invalid LLM response.
        
        Args:
            content: The invalid response content
            truncate_length: Max length for content in hint
            
        Returns:
            Formatted hint message
        """
        content_truncated = content[:truncate_length]
        
        return f"""你的回复格式不正确。请严格按照以下格式之一回复：
1. 如果任务完成：DONE: 结果总结
2. 如果需要继续工作：WORKING: 下一步计划
3. 如果需要调用工具：使用原生 tool calling 机制
4. 如果遇到错误无法继续：NEED_SKILL: 错误描述

你之前的回复是：{content_truncated}"""

    @classmethod
    def get_empty_response_hint(cls) -> str:
        """
        Build a hint message for empty LLM response.
        
        Returns:
            Formatted hint message
        """
        return """你的回复为空。请重新回复，按照以下格式之一：
1. 如果任务完成：DONE: 结果总结
2. 如果需要继续工作：WORKING: 下一步计划
3. 如果需要调用工具：使用原生 tool calling 机制
4. 如果遇到错误无法继续：NEED_SKILL: 错误描述"""

    @classmethod
    def get_continue_task_prompt(cls, working_msg: str) -> str:
        """
        Build a prompt to continue task execution.
        
        Args:
            working_msg: The working message from LLM
            
        Returns:
            Formatted continue prompt
        """
        return f"继续执行任务。{working_msg}"

    @classmethod
    def get_skill_installed_prompt(cls, skill_name: str, skill_description: str, task: str, tools_description: str = None) -> str:
        """
        Build a prompt after skill installation.
        
        Args:
            skill_name: Name of installed skill
            skill_description: Description of installed skill
            task: Original task
            tools_description: (Deprecated) Updated tools description - no longer used with native tool calling
            
        Returns:
            Formatted prompt
        """
        return f"""我已自动安装了技能「{skill_name}」！

技能描述: {skill_description}

请使用新安装的技能继续完成以下任务:
{task}

工具已通过 API 原生 tool calling 机制提供，请继续执行任务。"""

    @classmethod
    def get_streaming_tool_result_hint(cls, result: dict, truncate_length: int = 500) -> str:
        """
        Build a hint message for streaming executor after tool execution.
        
        Args:
            result: Tool execution result
            truncate_length: Max length for result in hint
            
        Returns:
            Formatted hint message
        """
        import json
        result_str = json.dumps(result)[:truncate_length]
        
        # Check if this is an ask_user tool result - user's answer needs to be processed
        if result.get("answer") is not None and result.get("question") is not None:
            user_answer = result.get("answer", "")
            question = result.get("question", "")
            return f"""用户回答了你的问题：
问题: {question}
用户回答: {user_answer}

重要：用户的回答是任务的输入，你需要根据用户的回答继续执行任务。
- 请根据用户的回答决定下一步操作
- 如果需要调用工具 → 使用原生 tool calling
- 如果任务已完成 → 返回 DONE: 执行结果总结"""
        
        return f"""工具执行结果：{result_str}

请立即判断任务是否已完成：
- 如果工具已成功执行 → 必须返回 DONE: 执行结果总结
- 如果还需要获取页面内容 → 返回 WORKING: 需要做什么，然后调用获取内容的工具
- 如果需要调用工具 → 使用原生 tool calling"""
