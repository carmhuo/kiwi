from typing import List

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain.retrievers import EnsembleRetriever
from langchain_core.vectorstores import VectorStore

from kiwi.embedding import ONNXMiniLM_L6_V2


class Retriever:
    """ 通用检索系统
        1. 词法搜索索引, 基于 BM25 and TF-IDF
        2. 向量索引，使用嵌入模型将文档压缩为高维矢量表示。这允许使用余弦相似度等简单的数学运算对嵌入向量进行有效的相似性搜索。
        3. 关系数据库查询
        参考：https://python.langchain.com/docs/concepts/retrieval/
    """

    def __init__(self, vector_store: VectorStore, embedding: Embeddings, config: Dict[str, Any]):
        self.embeddings = embedding
        self.vector_store = vector_store

        self.ensemble_retriever = EnsembleRetriever(
            retrievers=[bm25_retriever, faiss_retriever], weights=[0.5, 0.5]
        )

        self.project_id = config.get("project_id", None)

        self.n_results = config.get("n_results", 10)

    def retrieve_info_use_BM25(self, query: str, n_results: int = 10) -> List[Document]:
        """检索与查询相关的各类信息.
        Returns: 包含查询-SQL对、表结构、业务文档的字典
        """

        pass

    async def retrieve_relevant_info(self, query: str, n_results: int = 3) -> List[Document]:
        """检索与查询相关的各类信息.
        Returns: 包含查询-SQL对、表结构、业务文档的字典
        """

        docs = await self.ensemble_retriever.ainvoke(query)

        return docs