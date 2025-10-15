import logging
import json
from typing import Dict, Any, Optional
from kiwi.core.cache import CacheManager
from kiwi.agents.fallback import FallbackStrategy
from kiwi.agents.prompts import CHART_PROMPT
from kiwi.core.exceptions import ChartGenerationError
from kiwi.core.retry import async_retry
from kiwi.core.monitoring import timing_metrics, CHART_GEN_LATENCY

logger = logging.getLogger(__name__)


class ChartGeneratorAgent:
    """
    图表生成Agent，负责根据查询结果生成可视化图表配置

    生产级特性：
    1. 多模型降级策略
    2. 结果缓存
    3. 重试机制
    4. 结构化输出验证
    5. 监控集成
    6. 错误处理
    """

    # 支持的图表类型及其验证规则
    CHART_TYPES = {
        "bar": {"required": ["x_axis", "y_axis"], "optional": ["group_by"]},
        "line": {"required": ["x_axis", "y_axis"], "optional": ["group_by"]},
        "pie": {"required": ["category", "value"], "optional": []},
        "scatter": {"required": ["x_axis", "y_axis"], "optional": ["size"]},
        "table": {"required": [], "optional": ["columns"]},
        "heatmap": {"required": ["x_axis", "y_axis", "value"], "optional": []},
        "histogram": {"required": ["value"], "optional": ["bins"]},
    }

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.cache = CacheManager()
        self.fallback = FallbackStrategy(
            primary_model=config.get("model", "gpt-4"),
            fallback_model=config.get("fallback_model", "gpt-3.5-turbo")
        )

    @async_retry(max_retries=3, initial_delay=0.2, backoff_factor=1.5)
    async def generate_chart_config(
            self,
            query: str,
            query_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        生成图表配置
        :param query: 用户原始问题
        :param query_result: SQL查询结果
        :return: 图表配置字典
        """
        cache_key = f"chart:{query[:50]}:{hash(json.dumps(query_result['data'][:3]))}"

        # 检查缓存
        if cached := await self.cache.get(cache_key):
            logger.info(f"Chart config cache hit for query: {query[:50]}")
            return json.loads(cached)

        # 监控性能
        async with timing_metrics(CHART_GEN_LATENCY, {"chart_type": "auto"}):
            # 尝试自动选择简单图表类型
            simple_chart = self._try_simple_chart_type(query, query_result)
            if simple_chart:
                return simple_chart

            # 调用LLM生成复杂图表配置
            return await self._generate_with_llm(query, query_result, cache_key)

    def _try_simple_chart_type(
            self,
            query: str,
            query_result: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        尝试自动选择简单图表类型，避免调用LLM
        """
        # 如果数据量很小，直接返回表格
        if len(query_result["data"]) <= 5:
            return {
                "type": "table",
                "title": f"{query} - 结果",
                "data": query_result["data"],
                "columns": query_result["columns"]
            }

        # 检测时间序列数据
        time_columns = [col for col in query_result["columns"]
                        if any(keyword in col.lower() for keyword in ["date", "time", "year", "month"])]

        # 检测数值列
        numeric_columns = [col for col in query_result["columns"]
                           if any(isinstance(row[col], (int, float))
                                  for row in query_result["data"][:5])]

        # 如果有时间列和数值列，生成折线图
        if time_columns and numeric_columns:
            return {
                "type": "line",
                "title": query,
                "x_axis": time_columns[0],
                "y_axis": numeric_columns[0],
                "data": query_result["data"],
                "options": {
                    "tooltip": {"trigger": "axis"},
                    "legend": {"data": [numeric_columns[0]]}
                }
            }

        # 如果有分类列和数值列，生成柱状图
        category_columns = [col for col in query_result["columns"]
                            if len(set(row[col] for row in query_result["data"])) <= 10]

        if category_columns and numeric_columns:
            return {
                "type": "bar",
                "title": query,
                "x_axis": category_columns[0],
                "y_axis": numeric_columns[0],
                "data": query_result["data"],
                "options": {
                    "tooltip": {"trigger": "axis"},
                    "legend": {"data": [numeric_columns[0]]}
                }
            }

        return None

    async def _generate_with_llm(
            self,
            query: str,
            query_result: Dict[str, Any],
            cache_key: str
    ) -> Dict[str, Any]:
        """
        使用LLM生成图表配置
        """
        # 准备提示词
        prompt = self._build_prompt(query, query_result)

        try:
            # 调用LLM
            response = await self.fallback.call_llm(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.config.get("max_tokens", 500),
                temperature=self.config.get("temperature", 0.2)
            )

            # 提取JSON配置
            chart_config = self._extract_chart_config(response.choices[0].message.content)

            # 验证配置
            self._validate_chart_config(chart_config, query_result)

            # 添加原始数据
            chart_config["data"] = query_result["data"]

            # 缓存结果
            await self.cache.set(cache_key, json.dumps(chart_config), ttl=3600)

            return chart_config
        except Exception as e:
            logger.error(f"Chart generation failed: {str(e)}")
            # 降级为表格视图
            return self._fallback_table_config(query, query_result)

    def _build_prompt(self, query: str, query_result: Dict[str, Any]) -> str:
        """
        构建图表生成的提示词
        """
        # 提取列名
        columns = query_result["columns"]

        # 提取数据样例（最多3行）
        sample_data = []
        for i, row in enumerate(query_result["data"]):
            if i >= 3:
                break
            sample_data.append({k: v for k, v in row.items()})

        # 构建提示词
        return CHART_PROMPT.format(
            query=query,
            columns=", ".join(columns),
            sample_data=json.dumps(sample_data, indent=2),
            row_count=len(query_result["data"])
        )

    def _extract_chart_config(self, text: str) -> Dict[str, Any]:
        """
        从LLM响应中提取图表配置
        """
        # 尝试找到JSON代码块
        start_index = text.find("```json")
        if start_index == -1:
            start_index = text.find("{")
            end_index = text.rfind("}")
            if start_index == -1 or end_index == -1:
                raise ChartGenerationError("未找到有效的JSON配置")
            json_str = text[start_index:end_index + 1]
        else:
            end_index = text.find("```", start_index + 7)
            if end_index == -1:
                raise ChartGenerationError("JSON代码块未正确结束")
            json_str = text[start_index + 7:end_index].strip()

        try:
            # 尝试解析JSON
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {json_str}, 错误: {str(e)}")
            raise ChartGenerationError("图表配置JSON格式无效")

    def _validate_chart_config(
            self,
            config: Dict[str, Any],
            query_result: Dict[str, Any]
    ):
        """
        验证图表配置是否有效
        """
        # 检查基本字段
        if "type" not in config:
            raise ChartGenerationError("图表配置缺少'type'字段")

        chart_type = config["type"].lower()

        # 检查是否支持该图表类型
        if chart_type not in self.CHART_TYPES:
            raise ChartGenerationError(f"不支持的图表类型: {chart_type}")

        # 获取验证规则
        rules = self.CHART_TYPES[chart_type]

        # 检查必填字段
        for field in rules["required"]:
            if field not in config:
                raise ChartGenerationError(f"图表配置缺少必填字段: {field}")

        # 检查字段是否存在于数据列中
        all_fields = rules["required"] + rules["optional"]
        for field in all_fields:
            if field in config and config[field]:
                field_value = config[field]
                # 处理数组字段
                if isinstance(field_value, list):
                    for item in field_value:
                        if item not in query_result["columns"]:
                            raise ChartGenerationError(
                                f"字段 '{item}' 在查询结果中不存在"
                            )
                elif field_value not in query_result["columns"]:
                    raise ChartGenerationError(
                        f"字段 '{field_value}' 在查询结果中不存在"
                    )

        # 特殊验证：饼图的值字段必须是数值
        if chart_type == "pie":
            value_field = config.get("value")
            if value_field:
                sample_value = next(
                    (row[value_field] for row in query_result["data"]),
                    None
                )
                if not isinstance(sample_value, (int, float)):
                    raise ChartGenerationError(
                        f"饼图的值字段 '{value_field}' 必须是数值类型"
                    )

    def _fallback_table_config(
            self,
            query: str,
            query_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        降级方案：返回表格配置
        """
        logger.warning("使用降级表格配置")
        return {
            "type": "table",
            "title": f"{query} - 结果",
            "data": query_result["data"],
            "columns": query_result["columns"]
        }