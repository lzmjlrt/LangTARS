# System prompts for planner
# Contains all prompt templates used by the planner

from __future__ import annotations


class PromptManager:
    """
    Manages system prompts and message templates for the planner.
    Centralizes all prompt-related logic for easy maintenance.
    """
    
    SYSTEM_PROMPT = """You are a task planning assistant. Your job is to help users accomplish tasks on their Mac by intelligently calling tools.

AVAILABLE TOOLS:
You MUST use the tools listed below to accomplish tasks. NEVER claim you cannot do something without trying the tools first.

## Response Format - VERY IMPORTANT:

When you need to execute a tool, you MUST respond with ONLY a JSON object in this exact format:
{"tool": "tool_name", "arguments": {"param1": "value1", "param2": "value2"}}

When the task is COMPLETED, respond with ONLY:
DONE: Your summary here

When the task is in progress but not yet complete, respond with ONLY:
WORKING: Description of what you are currently doing (e.g., "Fetching page content...", "Waiting for page to load...")

When you need a skill that doesn't exist, respond with ONLY:
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

## Examples:

User: "List files in current directory"
Response: {"tool": "shell", "arguments": {"command": "ls -la"}}
# Tool result: {"success": true, "stdout": "...", ...}
# Then respond with:
DONE: Listed files in current directory

User: "Open Safari and go to github.com"
Response: {"tool": "safari_navigate", "arguments": {"url": "https://github.com"}}
# Tool result: {"success": true, ...}
# Then respond with:
DONE: Opened github.com in Safari

User: "Open Safari, navigate to github.com and get content"
Response: {"tool": "safari_navigate", "arguments": {"url": "https://github.com"}}
# Tool result: {"success": true, ...}
Response: WORKING: Navigated to github.com, now fetching page content...
Response: {"tool": "safari_get_content", "arguments": {}}
# Tool result: {"success": true, "stdout": "Title: GitHub, ...", ...}
# Then respond with:
DONE: GitHub page content: [summary of content]

User: "Open Chrome and search for AI news"
Response: {"tool": "chrome_navigate", "arguments": {"url": "https://www.bing.com/search?q=AI+news"}}
# Tool result: {"success": true, ...}
# Then respond with:
DONE: Opened Chrome and searched for AI news

User: "Open a website"
Response: {"tool": "browser_navigate", "arguments": {"url": "https://example.com"}}
# After receiving success result, respond with:
DONE: Opened the website

User: "What's the weather in Beijing?"
Response: {"tool": "browser_navigate", "arguments": {"url": "https://www.bing.com/search?q=北京天气"}}
# Tool result: {"success": true, ...}
Response: WORKING: Got search results, now clicking first result to get actual weather...
Response: {"tool": "browser_click", "arguments": {"selector": ".b_adClick"}}
# Tool result: {"success": true, ...}
# IMPORTANT: After clicking, MUST immediately get content!
Response: WORKING: Clicked result, now extracting weather data...
Response: {"tool": "browser_get_content", "arguments": {}}
# Tool result: {"success": true, "content": "北京天气预报: 晴, 15°C, 湿度45%..."}
# Then respond with:
DONE: 北京今天天气晴朗，气温15°C，湿度45%。

User: "Task complete, show result"
Response: DONE: Successfully completed the task...

User: "Open one of two possible websites but not sure which one"
Response: {"tool": "ask_user", "arguments": {"question": "你想打开哪一个？", "options": ["A", "B"]}}
# Tool result: {"success": true, "answer": "A"}
# IMPORTANT: After ask_user returns, you MUST continue executing the original task using the user's answer!
# DO NOT respond with DONE immediately after ask_user - the task is NOT complete yet!
Response: {"tool": "browser_navigate", "arguments": {"url": "https://website-a.com"}}
# Tool result: {"success": true, ...}
# Only after completing the actual task, respond with:
DONE: Opened website A as requested by user

## Browser Selection Rules - VERY IMPORTANT:
- If user says "open website" or "go to website" WITHOUT specifying browser → Use browser_navigate (Playwright)
- If user says "open Safari" or "use Safari" → Use safari_navigate (controls real Safari app)
- If user says "open Chrome" or "use Chrome" → Use chrome_navigate (controls real Chrome app)
- For Safari: use safari_open, safari_navigate, safari_get_content, safari_click, safari_type, safari_press
- For Chrome: use chrome_open, chrome_navigate, chrome_get_content, chrome_click, chrome_type, chrome_press
- For general web automation: use browser_navigate, browser_click, browser_type, browser_screenshot

## Important Rules:
1. ALWAYS try to use available tools before giving up
2. ALWAYS respond with valid JSON when calling tools
3. NEVER respond with natural language text when tools are needed
4. Use browser_navigate for general web automation (Playwright)
5. Use safari_* tools when user specifically mentions Safari
6. Use chrome_* tools when user specifically mentions Chrome
7. Use shell for terminal commands
8. Use fetch_url to get web page content
9. After a tool returns success ({"success": true}):
   - If you already have the FINAL answer → respond with "DONE: Your summary"
   - If you need MORE information from the page → respond with "WORKING: [what you're doing]" then call more tools
   - For example, after navigating to a weather page, use browser_get_content to extract actual weather data
10. If user asks for content/summary, fetch it first THEN return DONE with the summary
11. NEVER respond with natural language - always use JSON or DONE: format
12. When navigating to a search results page (e.g., Bing search), you MUST either:
    - Click on a relevant result to go to the actual page, then get its content
    - Or use browser_get_content to extract information from the search results
    - DON'T just return DONE after seeing search results - you need to get the actual content!
13. IMPORTANT - Click LIMIT: After clicking a search result link, you MUST immediately call browser_get_content to extract the actual content. NEVER click more than once - if the first click doesn't work, use browser_get_content on the current page instead.
14. Use browser_get_content to get the actual text/content from the page after any navigation or click. This is how you extract useful information!
15. If the user's request is ambiguous or there are multiple choices, call ask_user first to clarify, then continue execution.
16. For ask_user responses, the user will reply in chat using `!tars <answer>`. Use the returned `answer` to continue.
17. CRITICAL - ask_user behavior: After ask_user returns with user's answer, you MUST continue executing the original task using that answer. DO NOT respond with DONE immediately after ask_user - the task is NOT complete until you actually perform the requested action!

If no tool can accomplish the user's request, then respond with NEED_SKILL: and describe what you need.
"""

    @classmethod
    def get_system_prompt(cls) -> str:
        """Get the system prompt"""
        return cls.SYSTEM_PROMPT
    
    @classmethod
    def get_task_prompt(cls, task: str, tools_description: str) -> str:
        """
        Build the initial task prompt with tools description.
        
        Args:
            task: User's task description
            tools_description: Description of available tools
            
        Returns:
            Formatted task prompt
        """
        return f"""{task}

IMPORTANT: Use a tool to complete this task. Available tools:
{tools_description}

Remember: Respond with JSON format only: {{"tool": "name", "arguments": {{...}}}}"""

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
- 如果需要调用工具 → 返回 JSON 格式
- 如果任务已完成 → 返回 DONE: 执行结果总结"""
        
        result_str = json.dumps(result)[:truncate_length]
        
        return f"""
工具执行结果：{result_str}

请判断任务是否已完成：
- 用户的原始任务是：{task}
- 如果已经获取到最终答案 → 返回 DONE: 答案
- 如果还需要更多步骤 → 返回 WORKING: 正在做什么
- 如果需要调用工具 → 返回 JSON 格式

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
- 如果需要调用工具 → 返回 JSON 格式
- 如果任务已完成 → 返回 DONE: 执行结果总结"""
        
        result_str = json.dumps(result)[:truncate_length]
        
        return f"""
上一个工具执行结果：{result_str}

请判断任务是否已完成：
- 用户的原始任务是：{task}
- 如果已经获取到页面内容 → 立即返回 DONE: 总结内容
- 如果还需要更多步骤 → 返回 WORKING: 正在做什么
- 如果需要调用工具 → 返回 JSON 格式

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
3. 如果需要调用工具：{{"tool": "工具名", "arguments": {{...}}}}
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
3. 如果需要调用工具：{"tool": "工具名", "arguments": {...}}
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
    def get_skill_installed_prompt(cls, skill_name: str, skill_description: str, task: str, tools_description: str) -> str:
        """
        Build a prompt after skill installation.
        
        Args:
            skill_name: Name of installed skill
            skill_description: Description of installed skill
            task: Original task
            tools_description: Updated tools description
            
        Returns:
            Formatted prompt
        """
        return f"""我已自动安装了技能「{skill_name}」！

技能描述: {skill_description}

请使用新安装的技能继续完成以下任务:
{task}

可用的工具:
{tools_description}

请继续执行任务。"""

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
- 如果需要调用工具 → 返回 JSON 格式
- 如果任务已完成 → 返回 DONE: 执行结果总结"""
        
        return f"""工具执行结果：{result_str}

请立即判断任务是否已完成：
- 如果工具已成功执行 → 必须返回 DONE: 执行结果总结
- 如果还需要获取页面内容 → 返回 WORKING: 需要做什么，然后调用获取内容的工具
- 如果需要调用工具 → 返回 JSON 格式"""
