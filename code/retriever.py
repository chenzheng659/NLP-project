"""
retriever.py - 代码检索模块
封装 project/retriever_and_schemas.py 中的 CodeRetriever，
对外只暴露一个简洁的 search_code() 函数。
"""
import sys
from pathlib import Path
from typing import Optional

# 将 project 目录加入路径，复用已有的 CodeRetriever
sys.path.insert(0, str(Path(__file__).parent.parent / "project"))
from retriever_and_schemas import CodeRetriever

from . import config

_retriever_instance: Optional[CodeRetriever] = None


def get_retriever() -> CodeRetriever:
    """单例：全局只初始化一次，避免重复加载模型"""
    global _retriever_instance
    if _retriever_instance is None:
        print("正在初始化 CodeRetriever（首次运行会下载模型）...")
        _retriever_instance = CodeRetriever(
            dataset_path=config.DATASET_PATH,
            embed_model_name=config.EMBED_MODEL_NAME,
            rerank_model_name=config.RERANK_MODEL_NAME,
        )
        print("CodeRetriever 初始化完成。")
    return _retriever_instance


def search_code(instruction: str) -> Optional[str]:
    """
    根据自然语言指令检索最匹配的代码片段。

    Returns:
        匹配到的代码字符串；若无匹配则返回 None（触发降级纯生成）
    """
    retriever = get_retriever()
    results = retriever.search(
        query=instruction,
        top_k=1,
        recall_k=config.RECALL_K,
        rerank_threshold=config.RERANK_THRESHOLD,
    )
    if results:
        return results[0].get("code", "")
    return None
