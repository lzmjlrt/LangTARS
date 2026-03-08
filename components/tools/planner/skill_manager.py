# Skill management for planner
# Handles skill search, installation, and auto-retry logic

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from components.tools.planner_tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class SkillManager:
    """
    Manages skill search, installation, and auto-retry functionality.
    Works with the tool registry's skill loader to provide dynamic capabilities.
    """
    
    def __init__(self, registry: 'ToolRegistry | None' = None):
        """
        Initialize skill manager.
        
        Args:
            registry: Tool registry with skill loader
        """
        self._registry = registry
    
    def set_registry(self, registry: 'ToolRegistry') -> None:
        """Set the tool registry"""
        self._registry = registry
    
    @property
    def skill_loader(self):
        """Get the skill loader from registry"""
        if self._registry:
            return self._registry._skill_loader
        return None
    
    async def search_skills(self, query: str) -> list:
        """
        Search for skills matching a query.
        
        Args:
            query: Search query
            
        Returns:
            List of matching skills
        """
        if not self.skill_loader:
            logger.debug("Skill loader not available")
            return []
        
        try:
            logger.info(f"正在搜索Skill: {query}")
            found_skills = await self.skill_loader.search_skills(query)
            logger.debug(f"搜索结果: {len(found_skills)} 个skills found")
            return found_skills
        except Exception as e:
            logger.debug(f"Failed to search skills: {e}")
            return []
    
    async def install_skill(self, skill_name: str) -> dict[str, Any]:
        """
        Install a skill by name.
        
        Args:
            skill_name: Name of the skill to install
            
        Returns:
            Installation result dict
        """
        if not self.skill_loader:
            return {"success": False, "error": "Skill loader not available"}
        
        try:
            logger.info(f"正在安装技能: {skill_name}")
            result = await self.skill_loader.install_skill(skill_name)
            if result.get("success"):
                logger.info(f"技能 {skill_name} 安装成功")
            else:
                logger.info(f"技能安装失败: {result.get('error')}")
            return result
        except Exception as e:
            logger.debug(f"Install failed: {e}")
            return {"success": False, "error": str(e)}
    
    def try_auto_install_sync(self, skill_name: str) -> dict[str, Any]:
        """
        Try to automatically install a skill (synchronous wrapper).
        
        Args:
            skill_name: Name of the skill to install
            
        Returns:
            Installation result dict
        """
        if not self.skill_loader:
            return {"success": False, "error": "Skill loader not available"}
        
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                self.skill_loader.install_skill(skill_name)
            )
            loop.close()
            return result
        except Exception as e:
            logger.debug(f"Auto-install failed: {e}")
            return {"success": False, "error": str(e)}
    
    async def try_auto_install_and_retry(
        self,
        skill_needed: str,
        task: str,
        execute_callback,
    ) -> str | None:
        """
        Try to automatically install a skill and retry the task.
        
        Args:
            skill_needed: Description of needed skill
            task: Original task description
            execute_callback: Callback to continue execution after install
            
        Returns:
            Result if successful, None if failed
        """
        if not self._registry or not self.skill_loader:
            logger.debug("Skill loader not available for auto-install")
            return None
        
        try:
            # Search for relevant skills
            found_skills = await self.search_skills(skill_needed)
            
            if not found_skills:
                logger.info(f"未找到匹配的Skill: {skill_needed}")
                return None
            
            # Try to install the first matching skill
            first_skill = found_skills[0]
            logger.info(f"找到匹配的技能: {first_skill.name}，尝试自动安装...")
            
            install_result = await self.install_skill(first_skill.name)
            
            if not install_result.get("success"):
                logger.info(f"安装失败: {install_result.get('error')}")
                return None
            
            logger.info(f"技能 {first_skill.name} 安装成功！正在重新加载工具...")
            
            # Reload dynamic tools to include the new skill
            try:
                dynamic_tools = await self._registry.load_dynamic_tools()
                if dynamic_tools:
                    logger.debug(f"重新加载了 {len(dynamic_tools)} 个动态工具")
            except Exception as e:
                logger.debug(f"重新加载动态工具失败: {e}")
            
            # Get updated tools description
            try:
                tools_description = self._registry.get_tools_description()
            except Exception as e:
                logger.debug(f"获取 tools_description 失败: {e}")
                tools_description = ""
            
            # Call the execute callback to continue
            if execute_callback:
                return await execute_callback(
                    skill_name=first_skill.name,
                    skill_description=first_skill.description,
                    tools_description=tools_description,
                )
            
            return None
            
        except Exception as e:
            logger.debug(f"Auto-install and retry failed: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def generate_skill_suggestion(self, skill_needed: str) -> str:
        """
        Generate a suggestion message when a skill is needed.
        
        Args:
            skill_needed: Description of needed skill
            
        Returns:
            Formatted suggestion message
        """
        skill_info = ""
        found_skills = []
        
        if self.skill_loader:
            try:
                import asyncio
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                found_skills = loop.run_until_complete(
                    self.skill_loader.search_skills(skill_needed)
                )
                loop.close()
                
                if found_skills:
                    skill_info = "\n\n找到以下相关 Skills:\n"
                    for skill in found_skills[:5]:  # Show up to 5 skills
                        skill_info += f"- {skill.name}: {skill.description}\n"
                    
                    # Try to auto-install the first matching skill
                    first_skill = found_skills[0]
                    install_result = self.try_auto_install_sync(first_skill.name)
                    if install_result.get("success"):
                        return f"""我发现了相关技能「{first_skill.name}」，正在自动安装...

安装成功！技能「{first_skill.name}」已安装。

请再次发送任务，我将使用新安装的技能来完成你的请求。
"""
            except Exception as e:
                logger.debug(f"Failed to search skills: {str(e)}")
        
        # If no skills found or auto-install failed, provide manual instructions
        return f"""抱歉，我无法完成这个任务，因为缺少必要的工具/技能。

需要的技能: {skill_needed}{skill_info}

"""
    
    def is_error_state(self, skill_needed: str) -> bool:
        """
        Check if the skill_needed message indicates an error state.
        
        Args:
            skill_needed: The skill needed message
            
        Returns:
            True if this is an error state
        """
        error_keywords = [
            '无法连接', '网络', 'error', 'failed', '失败', '超时', 'timeout'
        ]
        skill_lower = skill_needed.lower()
        return any(keyword in skill_lower for keyword in error_keywords)


# Global skill manager instance
_skill_manager: SkillManager | None = None


def get_skill_manager(registry: 'ToolRegistry | None' = None) -> SkillManager:
    """
    Get the global skill manager instance.
    
    Args:
        registry: Optional tool registry to set
        
    Returns:
        SkillManager instance
    """
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager(registry)
    elif registry:
        _skill_manager.set_registry(registry)
    return _skill_manager
