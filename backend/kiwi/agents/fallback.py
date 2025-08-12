import openai
import logging
from typing import List, Dict, Any

from kiwi.core.config import logger


class FallbackStrategy:
    def __init__(self, primary_model: str, fallback_model: str):
        self.primary_model = primary_model
        self.fallback_model = fallback_model

    async def call_llm(self, messages: List[Dict[str, str]], **kwargs) -> Any:
        models = [self.primary_model, self.fallback_model]

        for model in models:
            try:
                return await self._call_openai(model, messages, **kwargs)
            except Exception as e:
                logger.warning(f"Model {model} failed: {str(e)}")
                if model == models[-1]:
                    raise
                logger.info(f"Trying fallback model: {models[models.index(model) + 1]}")

    async def _call_openai(self, model: str, messages: List[Dict[str, str]], **kwargs) -> Any:
        return await openai.ChatCompletion.acreate(
            model=model,
            messages=messages,
            **kwargs
        )