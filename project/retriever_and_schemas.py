import json
import torch
import faiss
import numpy as np
from typing import Optional, List, Dict
from pydantic import BaseModel, Field

# 引入 sentence_transformers 极大简化编码流程，并提供更好的 Pooling 策略
from sentence_transformers import SentenceTransformer, CrossEncoder

class EditRequest(BaseModel):
    instruction: str = Field(..., description="自然语言需求或编辑指令")
    source_code: Optional[str] = Field(None, description="原始代码（可选）。如果有，则进入模式二；如果为空，则进入模式一。")

class EditResponse(BaseModel):
    final_code: str = Field(..., description="系统最终输出的代码")
    retrieved_code: Optional[str] = Field(None, description="模式一下检索到的基础草稿，模式二下为None")
    patch_generated: Optional[str] = Field(None, description="LLM生成的代码补丁片段")
    mode_used: str = Field(..., description="当前使用的模式：'retrieval_generation' 或 'direct_edit'")

class CodeRetriever:
    def __init__(self, 
                 dataset_path: str, 
                 embed_model_name: str = "BAAI/bge-m3", 
                 rerank_model_name: str = "BAAI/bge-reranker-v2-m3"):
        
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading embedding model [{embed_model_name}] on {self.device}...")
        # Bi-Encoder: 用于第一阶段高效向量召回
        self.embedder = SentenceTransformer(embed_model_name, device=self.device)
        
        print(f"Loading reranker model [{rerank_model_name}] on {self.device}...")
        # Cross-Encoder: 用于第二阶段高精度重排
        self.reranker = CrossEncoder(rerank_model_name, device=self.device)

        self.code_data: List[Dict] = []
        self.documents: List[str] = []
        self.index = None
        self.embedding_dim = self.embedder.get_sentence_embedding_dimension()
        
        self._load_and_index_data(dataset_path)

    def _format_document(self, item: Dict) -> str:
        """
        不再破坏性地拆分权重，而是格式化为结构化文本，让 Transformer 的注意力机制自己去理解。
        保留代码中的符号、缩进和短变量名，这对代码语义至关重要。
        """
        func_name = item.get('function_name', '').strip()
        docstring = item.get('docstring', '').strip()
        code = item.get('code', '').strip()
        
        # 构建统一的上下文供模型阅读
        formatted_text = f"Function Name: {func_name}\nDescription: {docstring}\nCode Implementation:\n{code}"
        return formatted_text

    def _load_and_index_data(self, dataset_path: str):
        with open(dataset_path, 'r', encoding='utf-8') as f:
            self.code_data = json.load(f)
        
        if not self.code_data:
            raise ValueError("代码库为空。")

        # 1. 格式化文档
        self.documents = [self._format_document(item) for item in self.code_data]
        
        # 2. 批量生成向量 (SentenceTransformer 内部优化了 batch 处理和 normalize)
        print("Encoding dataset vectors...")
        embeddings = self.embedder.encode(
            self.documents, 
            batch_size=16, 
            show_progress_bar=True, 
            normalize_embeddings=True # 使用余弦相似度必须做 Normalize
        )
        
        # 3. 构建 FAISS 索引 (Inner Product 在 Normalized 后等价于 Cosine Similarity)
        self.index = faiss.IndexFlatIP(self.embedding_dim)
        self.index.add(np.array(embeddings).astype('float32'))
        print("FAISS index built successfully.")

    def search(self, query: str, top_k: int = 1, recall_k: int = 5, rerank_threshold: float = 0.0) -> List[Dict]:
        """
        双阶段检索：先通过向量召回 recall_k 个候选，再用 Cross-Encoder 精确计算相似度。
        """
        # BGE 模型对 query 有特定 prompt 建议以提升效果 (针对特定版本，M3通常不需要，但加入有助于代码检索)
        search_query = query
        query_embedding = self.embedder.encode([search_query], normalize_embeddings=True).astype('float32')
        
        # 召回较多候选样本（例如5个），避免漏掉字面差异大但语义相关的代码
        recall_scores, recall_indices = self.index.search(query_embedding, recall_k)
        
        candidate_docs = []
        candidate_items = []
        for idx in recall_indices[0]:
            if idx != -1:
                candidate_docs.append(self.documents[idx])
                candidate_items.append(self.code_data[idx])
                
        if not candidate_docs:
            return []

        # Cross-Encoder 将 query 和 doc 拼接输入模型，计算极准，但耗时较长，所以只对候选集处理
        pairs = [[query, doc] for doc in candidate_docs]
        rerank_scores = self.reranker.predict(pairs)
        
        # 将得分与候选合并并按得分倒序排序
        scored_candidates = list(zip(rerank_scores, candidate_items))
        scored_candidates.sort(key=lambda x: x[0], reverse=True)
        
        results = []
        best_score = scored_candidates[0][0]
        best_item = scored_candidates[0][1]
        
        print(f"Top Candidate: {best_item.get('function_name')} | 重排得分: {best_score:.4f} | 判定: {'命中' if best_score >= rerank_threshold else '拦截'}")
        
        # Reranker 的分数通常在 [-10, 10] 之间，如果为正表示相关，为负表示不相关，阈值一般设为 0 左右
        for score, item in scored_candidates[:top_k]:
            if score >= rerank_threshold:
                results.append(item)
                
        return results

if __name__ == "__main__":
    try:
        # 初始化 Retriever (首次运行会自动从 HuggingFace 下载模型)
        retriever = CodeRetriever(dataset_path="code.json")
        
        test_queries = [
            "Solve the 0/1 knapsack problem using dynamic programming",
            "Parse and extract email addresses",
            "Calculate the weighted average of a list", 
            "Implement a simple HTTP server",
            "Implement a function that, given a dataset, carries out a basic convolutional neural network training workflow"
        ]
        
        print("\n" + "="*50)
        for q in test_queries:
            print(f"\n查询: {q}")
            results = retriever.search(q, top_k=1, recall_k=5, rerank_threshold=0.5)
            
            if results:
                print(f"返回代码: {results[0]['function_name']}")
            else:
                print("返回结果: None (降级为纯生成模式)")
                
    except FileNotFoundError:
        print("未找到 code.json 文件。")