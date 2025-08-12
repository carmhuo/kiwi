"""Utility & helper functions."""
import os
from datetime import datetime
from functools import lru_cache
from typing import Generator, Optional

from langchain.chat_models import init_chat_model
from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage

from dotenv import load_dotenv

load_dotenv()  # load environment variables from .env


# Get current date in a readable format
def get_current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_current_date():
    return datetime.now().strftime("%B %d, %Y")


def get_message_text(msg: BaseMessage) -> str:
    """Get the text content of a message."""
    content = msg.content
    if isinstance(content, str):
        return content
    elif isinstance(content, dict):
        return content.get("text", "")
    else:
        txts = [c if isinstance(c, str) else (c.get("text") or "") for c in content]
        return "".join(txts).strip()


def _format_doc(doc: Document) -> str:
    """Format a single document as XML.

    Args:
        doc (Document): The document to format.

    Returns:
        str: The formatted document as an XML string.
    """
    metadata = doc.metadata or {}
    meta = "".join(f" {k}={v!r}" for k, v in metadata.items())
    if meta:
        meta = f" {meta}"

    return f"<document{meta}>\n{doc.page_content}\n</document>"


def format_docs(docs: Optional[list[Document]]) -> str:
    """Format a list of documents as XML.

    This function takes a list of Document objects and formats them into a single XML string.

    Args:
        docs (Optional[list[Document]]): A list of Document objects to format, or None.

    Returns:
        str: A string containing the formatted documents in XML format.

    Examples:
        >>> docs = [Document(page_content="Hello"), Document(page_content="World")]
        >>> print(format_docs(docs))
        <documents>
        <document>
        Hello
        </document>
        <document>
        World
        </document>
        </documents>

        >>> print(format_docs(None))
        <documents></documents>
    """
    if not docs:
        return "<documents></documents>"
    formatted = "\n".join(_format_doc(doc) for doc in docs)
    return f"""<documents>
{formatted}
</documents>"""


@lru_cache(maxsize=8)
def load_chat_model(
        fully_specified_name: Optional[str] = None,
        temperature: float = 0.7,
        provider: str = "openai",
        **kwargs
) -> BaseChatModel:
    """Load a chat model from a fully specified name.

    Args:
         fully_specified_name: Model identifier in 'provider/model' format.
            Falls back to MODEL_NAME env var if None.
        temperature (float, optional): The temperature to use for sampling. Defaults to 0.7.
        provider (str, optional): The provider name, e.g., 'openai', 'anthropic'.
        **kwargs: Additional model initialization parameters.
    """
    # 环境变量验证
    required_env_vars = {
        "openai": ["OPENAI_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
    }.get(provider.lower(), [])

    for var in required_env_vars:
        if var not in os.environ:
            raise ValueError(
                f"Missing required environment variable: {var}. "
                f"Please set it to use the {provider} provider."
            )

    model_name = (
            fully_specified_name
            or os.getenv("MODEL_NAME", "Qwen/Qwen2.5-32B-Instruct")
    )

    try:
        return init_chat_model(
            model=model_name,
            model_provider=provider,
            base_url=os.getenv("OPENAI_API_BASE"),
            temperature=temperature,
            **kwargs
        )
    except Exception as e:
        raise RuntimeError(
            f"Failed to initialize model {model_name} from {provider}: {str(e)}"
        ) from e


def check_model_health(model: BaseChatModel) -> bool:
    """Perform basic health check on the model"""
    try:
        return bool(model.generate(["ping"]))
    except Exception:
        return False
