import asyncio
import hashlib
import importlib
import logging
import os
import tarfile
import sys
from functools import cached_property
from pathlib import Path
from typing import List, Any, Optional, Literal

import numpy as np
import numpy.typing as npt
import httpx
from pydantic import BaseModel, PrivateAttr
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_random

from langchain_core.embeddings import Embeddings

Documents = List[str]
Space = Literal["cosine", "l2", "ip"]

logger = logging.getLogger(__name__)


def _verify_sha256(fname: str, expected_sha256: str) -> bool:
    sha256_hash = hashlib.sha256()
    with open(fname, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest() == expected_sha256


class ONNXMiniLM_L6_V2(BaseModel, Embeddings):
    MODEL_NAME: str = "all-MiniLM-L6-v2"
    DOWNLOAD_PATH: Path = Path.home() / ".cache" / "chroma" / "onnx_models" / "all-MiniLM-L6-v2"
    EXTRACTED_FOLDER_NAME: str = "onnx"
    ARCHIVE_FILENAME: str = "onnx.tar.gz"
    MODEL_DOWNLOAD_URL: str = (
        "https://chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz"
    )
    _MODEL_SHA256: str = "913d7300ceae3b2dbc2c50d1de4baacab4be7b9380491c27fab7418616a16ec3"

    # Pydantic private attributes for non-serializable dependencies
    _ort: Any = PrivateAttr()
    _Tokenizer: Any = PrivateAttr()
    _tqdm: Any = PrivateAttr()
    _preferred_providers: Optional[List[str]] = PrivateAttr(default=None)

    def __init__(self, preferred_providers: Optional[List[str]] = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._preferred_providers = preferred_providers
        self._initialize_dependencies()

    def _initialize_dependencies(self) -> None:
        """Import required modules and handle missing dependencies"""
        try:
            self._ort = importlib.import_module("onnxruntime")
        except ImportError:
            raise ImportError(
                "onnxruntime not installed. Install with: pip install onnxruntime"
            )

        try:
            tokenizers = importlib.import_module("tokenizers")
            self._Tokenizer = tokenizers.Tokenizer
        except ImportError:
            raise ImportError(
                "tokenizers not installed. Install with: pip install tokenizers"
            )

        try:
            tqdm = importlib.import_module("tqdm")
            self._tqdm = tqdm.tqdm
        except ImportError:
            # Fallback to simple progress bar if tqdm not available
            self._tqdm = lambda **kwargs: kwargs.get('iterable', None)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        self._download_model_if_not_exists()
        embeddings = self._forward(texts)
        return embeddings.tolist()

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]

    async def aembed_documents(self, texts: List[str]) -> List[List[float]]:
        return await asyncio.get_running_loop().run_in_executor(None, self.embed_documents, texts)

    async def aembed_query(self, text: str) -> List[float]:
        return await asyncio.get_running_loop().run_in_executor(None, self.embed_query, text)

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_random(min=1, max=3),
        retry=retry_if_exception(lambda e: "does not match expected SHA256" in str(e)),
    )
    def _download(self, url: str, fname: str, chunk_size: int = 1024) -> None:
        with httpx.stream("GET", url) as resp:
            total = int(resp.headers.get("content-length", 0))
            desc = f"Downloading {os.path.basename(fname)}"
            with open(fname, "wb") as file:
                for data in self._tqdm(
                        iterable=resp.iter_bytes(chunk_size=chunk_size),
                        desc=desc,
                        total=total,
                        unit="iB",
                        unit_scale=True,
                        unit_divisor=1024,
                        disable=not hasattr(self._tqdm, '__call__')
                ):
                    file.write(data)

        if not _verify_sha256(fname, self._MODEL_SHA256):
            os.remove(fname)
            raise ValueError("Downloaded model failed SHA256 verification")

    def _normalize(self, v: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
        norm = np.linalg.norm(v, axis=1)
        norm[norm == 0] = 1e-12
        return v / norm[:, np.newaxis]

    def _forward(
            self, documents: List[str], batch_size: int = 32
    ) -> npt.NDArray[np.float32]:
        all_embeddings = []
        for i in range(0, len(documents), batch_size):
            batch = documents[i: i + batch_size]
            encoded = [self.tokenizer.encode(d) for d in batch]

            for doc_tokens in encoded:
                if len(doc_tokens.ids) > self.max_tokens():
                    logger.warning(
                        f"Document truncated (max {self.max_tokens()} tokens): "
                        f"Actual {len(doc_tokens.ids)} tokens"
                    )

            input_ids = np.array([e.ids for e in encoded])
            attention_mask = np.array([e.attention_mask for e in encoded])

            onnx_input = {
                "input_ids": input_ids.astype(np.int64),
                "attention_mask": attention_mask.astype(np.int64),
                "token_type_ids": np.zeros_like(input_ids).astype(np.int64),
            }

            model_output = self.model.run(None, onnx_input)
            last_hidden_state = model_output[0]

            input_mask_expanded = np.broadcast_to(
                np.expand_dims(attention_mask, -1), last_hidden_state.shape
            )
            embeddings = np.sum(last_hidden_state * input_mask_expanded, 1) / np.clip(
                input_mask_expanded.sum(1), a_min=1e-9, a_max=None
            )

            embeddings = self._normalize(embeddings).astype(np.float32)
            all_embeddings.append(embeddings)

        return np.concatenate(all_embeddings)

    @cached_property
    def tokenizer(self) -> Any:
        tokenizer_path = self.DOWNLOAD_PATH / self.EXTRACTED_FOLDER_NAME / "tokenizer.json"
        tokenizer = self._Tokenizer.from_file(str(tokenizer_path))
        tokenizer.enable_truncation(max_length=256)
        tokenizer.enable_padding(pad_id=0, pad_token="[PAD]", length=256)
        return tokenizer

    @cached_property
    def model(self) -> Any:
        providers = self._preferred_providers or self._ort.get_available_providers()

        if not set(providers).issubset(set(self._ort.get_available_providers())):
            raise ValueError(
                f"Invalid providers. Available: {self._ort.get_available_providers()}"
            )

        so = self._ort.SessionOptions()
        so.log_severity_level = 3
        so.graph_optimization_level = self._ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        model_path = self.DOWNLOAD_PATH / self.EXTRACTED_FOLDER_NAME / "model.onnx"
        return self._ort.InferenceSession(
            str(model_path),
            providers=providers,
            sess_options=so,
        )

    def _download_model_if_not_exists(self) -> None:
        required_files = {
            self.DOWNLOAD_PATH / self.EXTRACTED_FOLDER_NAME / f
            for f in ["config.json", "model.onnx", "tokenizer.json"]
        }

        if all(f.exists() for f in required_files):
            return

        os.makedirs(self.DOWNLOAD_PATH, exist_ok=True)
        archive_path = self.DOWNLOAD_PATH / self.ARCHIVE_FILENAME

        if not archive_path.exists() or not _verify_sha256(str(archive_path), self._MODEL_SHA256):
            self._download(self.MODEL_DOWNLOAD_URL, str(archive_path))

        with tarfile.open(name=str(archive_path), mode="r:gz") as tar:
            if sys.version_info >= (3, 12):
                tar.extractall(path=str(self.DOWNLOAD_PATH), filter="data")
            else:
                tar.extractall(path=str(self.DOWNLOAD_PATH))

        # Verify extraction
        if not all(f.exists() for f in required_files):
            raise RuntimeError("Model extraction failed - missing files")

    def max_tokens(self) -> int:
        return 256

    @property
    def model_name(self) -> str:
        return self.MODEL_NAME

    def __call__(self, input: Documents) -> List[List[float]]:
        return self.embed_documents(input)


if __name__ == "__main__":

    # Initialize the embedding model
    embedder = ONNXMiniLM_L6_V2()

    # Embed documents
    documents = ["Hello world", "Machine learning is fascinating"]
    doc_embeddings = embedder.embed_documents(documents)
    print(doc_embeddings)

    # Embed a single query
    query = "What is AI?"
    query_embedding = embedder.embed_query(query)
    print(query_embedding)

    # Async embedding
    # async def async_embed():
    #     return await embedder.aembed_documents(documents)