from typing import Any, Dict

from sqlalchemy.ext.asyncio import AsyncSession

from kiwi.core.config import logger
from kiwi.crud.agent import AgentCRUD
from kiwi.schemas import AgentType


class ChartService:

    def __init__(self, db: AsyncSession, user_id: str):
        self.db = db
        self.user_id = user_id
        self.agent_crud = AgentCRUD()

    async def generate_chart(
            self,
            query: str,
            query_result: Dict[str, Any],
            project_id: str
    ) -> Dict[str, Any]:
        """Generate chart configuration from query results"""
        agent = await self.agent_crud.get_active_agent(
            self.db, project_id, AgentType.CHART_AGENT.value
        )

        if not agent:
            await logger.awarning("No chart generator agent configured, returning raw data")
            return self._create_fallback_chart(query, query_result)

        try:
            from kiwi.agents.chart_agent import ChartGeneratorAgent
            chart_agent = ChartGeneratorAgent(agent.config)
            return await chart_agent.generate_chart_config(query, query_result)
        except Exception as e:
            await logger.aerror(f"Chart generation failed: {str(e)}")
            return self._create_fallback_chart(query, query_result)

    def _create_fallback_chart(
            self,
            query: str,
            query_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create fallback table view when chart generation fails"""
        return {
            "type": "table",
            "title": f"{query} - Results",
            "data": query_result["data"],
            "columns": query_result["columns"]
        }

    def format_response(
            self,
            query_result: Dict[str, Any],
            chart_config: Dict[str, Any]
    ) -> str:
        """Format response based on chart type"""
        chart_type = chart_config.get("type")

        if chart_type == "table":
            return (
                f"Query successful, returned {len(query_result['data'])} records.\n"
                f"Fields: {', '.join(query_result['columns'])}"
            )
        elif chart_type in ["bar", "line"]:
            title = chart_config.get("title", "Analysis Results")
            x_axis = chart_config.get("x_axis", "X Axis")
            y_axis = chart_config.get("y_axis", "Y Axis")
            y_axis = "、".join(y_axis) if isinstance(y_axis, list) else y_axis
            group_by = chart_config.get("group_by")
            group_text = f", grouped by {group_by}" if group_by else ""

            return (
                f"{title}\n"
                f"• X Axis: {x_axis}\n"
                f"• Y Axis: {y_axis}{group_text}"
            )
        elif chart_type == "pie":
            title = chart_config.get("title", "Distribution Analysis")
            category = chart_config.get("category", "Category")
            value = chart_config.get("value", "Value")

            return (
                f"{title}\n"
                f"• Category: {category}\n"
                f"• Value: {value}"
            )

        return "Analysis completed. Please check the visualization below."
