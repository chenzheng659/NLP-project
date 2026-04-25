import json
import os
import re
import torch
import faiss
import numpy as np
from typing import Optional, List, Dict
from pydantic import BaseModel, Field
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
                 dataset_path: str = None,
                 dataset_paths: List[str] = None,
                 embed_model_name: str = "BAAI/bge-m3",
                 rerank_model_name: str = "BAAI/bge-reranker-v2-m3",
                 intent_threshold: float = 0.65):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        print(f"Loading embedding model [{embed_model_name}] on {self.device}...")
        self.embedder = SentenceTransformer(embed_model_name, device=self.device)
        print(f"Loading reranker model [{rerank_model_name}] on {self.device}...")
        self.reranker = CrossEncoder(rerank_model_name, device=self.device)

        self.code_data: List[Dict] = []
        self.documents: List[str] = []
        self.index = None
        self.embedding_dim = self.embedder.get_sentence_embedding_dimension()

        # 意图标签相关：现在存储的是“function_name + docstring”的自然语言标签
        self.intent_labels: List[str] = []
        self.intent_embeddings: np.ndarray = None
        self.intent_threshold = intent_threshold

        if dataset_paths:
            self._load_and_index_data(dataset_paths)
        elif dataset_path:
            self._load_and_index_data([dataset_path])
        else:
            raise ValueError("dataset_path 或 dataset_paths 必须提供其中之一")

    def _build_intent_labels(self):
        """
        用 function_name 和 docstring 拼接成自然语言标签，
        例如：'AStar: A* pathfinding algorithm implementation using heuristic-guided search.'
        这样匹配后返回的查询本身就有充分的语义，适合作为检索输入。
        """
        self.intent_labels = []
        for item in self.code_data:
            func_name = item.get('function_name', '').strip()
            doc = item.get('docstring', '').strip()
            # 组合为一段描述，既包含名字又包含功能说明
            label = f"{func_name}: {doc}" if doc else func_name
            if label:
                self.intent_labels.append(label)
        if self.intent_labels:
            print(f"Encoding {len(self.intent_labels)} intent labels...")
            self.intent_embeddings = self.embedder.encode(
                self.intent_labels, normalize_embeddings=True
            ).astype('float32')

    def _generate_phrase_candidates(self, query: str) -> List[str]:
        """
        生成候选短语集合：使用字符级滑动窗口，覆盖所有可能包含算法名称的子串。
        窗口长度从 3 到 30 个字符，步长为 2，兼顾效果与性能。
        """
        candidates = set()
        # 也保留整个句子，避免极端情况
        candidates.add(query)
        # 按常见标点切分后的片段也加入
        segments = re.split(r'[，。；：、,!?;:\s]+', query)
        for seg in segments:
            seg = seg.strip()
            if seg:
                candidates.add(seg)

        # 字符级滑动窗口
        for start in range(0, len(query), 2):
            for length in range(3, 31):
                end = start + length
                if end > len(query):
                    break
                candidates.add(query[start:end])
        return list(candidates)

    def _extract_algorithm_intent(self, query: str) -> str:
        """
        通过扫描语句中的候选短语，匹配最相似的代码库标签（function_name + docstring），
        提取出自然语言描述作为检索查询，确保语义丰富。
        """
        if self.intent_embeddings is None or len(self.intent_labels) == 0:
            return query

        # 1. 生成候选短语
        candidates = self._generate_phrase_candidates(query)
        if not candidates:
            return query

        # 2. 批量编码候选短语
        cand_embs = self.embedder.encode(candidates, normalize_embeddings=True).astype('float32')

        # 3. 计算所有候选与所有标签的相似度，取最大值
        scores = np.dot(cand_embs, self.intent_embeddings.T)   # [num_candidates, num_labels]
        best_cand_idx, best_label_idx = np.unravel_index(np.argmax(scores), scores.shape)
        best_score = scores[best_cand_idx, best_label_idx]

        if best_score >= self.intent_threshold:
            matched_label = self.intent_labels[best_label_idx]  # 这就是 "AStar: A* pathfinding..."
            phrase = candidates[best_cand_idx]
            print(f"Intent extracted: '{matched_label}' via phrase '{phrase}' (score: {best_score:.4f})")
            # 返回自然语言标签作为检索查询，而非原始函数名
            return matched_label

        # 降级：原句匹配度不够，直接使用原始查询
        return query

    def _format_document(self, item: Dict) -> str:
        func_name = item.get('function_name', '').strip()
        docstring = item.get('docstring', '').strip()
        code = item.get('code', '').strip()
        return f"Function Name: {func_name}\nDescription: {docstring}\nCode Implementation:\n{code}"

    def _load_and_index_data(self, dataset_paths: List[str]):
        merged: List[Dict] = []
        for path in dataset_paths:
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    items = json.load(f)
                raw_name = os.path.splitext(os.path.basename(path))[0]
                # 规范化文件名
                inferred_category = raw_name.rstrip("s") + "ion" if raw_name.endswith("ssion") else raw_name
                for item in items:
                    if 'category' not in item:
                        item = {**item, 'category': inferred_category}
                    merged.append(item)
                print(f"已加载数据集: {path}，共 {len(items)} 条记录")
            except Exception as e:
                print(f"[警告] 跳过数据集 {path}：{e}")

        if not merged:
            raise ValueError("所有数据集均为空或加载失败。")
        self.code_data = merged
        self.documents = [self._format_document(item) for item in self.code_data]

        print("Encoding dataset vectors...")
        embeddings = self.embedder.encode(
            self.documents, batch_size=16, show_progress_bar=True, normalize_embeddings=True
        )
        self.index = faiss.IndexFlatIP(self.embedding_dim)
        self.index.add(np.array(embeddings).astype('float32'))
        print("FAISS index built successfully.")

        # 构建意图标签库（使用 function_name + docstring）
        self._build_intent_labels()

    def search(self, query: str, top_k: int = 1, recall_k: int = 5, rerank_threshold: float = 0.0) -> List[Dict]:
        # 先提取算法意图作为检索查询（现在返回自然语言描述）
        search_query = self._extract_algorithm_intent(query)

        query_embedding = self.embedder.encode([search_query], normalize_embeddings=True).astype('float32')
        recall_scores, recall_indices = self.index.search(query_embedding, recall_k)

        candidate_docs = []
        candidate_items = []
        for idx in recall_indices[0]:
            if idx != -1:
                candidate_docs.append(self.documents[idx])
                candidate_items.append(self.code_data[idx])
        if not candidate_docs:
            return []

        # Cross-Encoder 重排
        pairs = [[search_query, doc] for doc in candidate_docs]
        rerank_scores = self.reranker.predict(pairs)
        scored_candidates = list(zip(rerank_scores, candidate_items))
        scored_candidates.sort(key=lambda x: x[0], reverse=True)

        results = []
        best_score = scored_candidates[0][0]
        best_item = scored_candidates[0][1]
        print(f"Top Candidate: {best_item.get('function_name')} | 重排得分: {best_score:.4f} | 判定: {'命中' if best_score >= rerank_threshold else '拦截'}")
        for score, item in scored_candidates[:top_k]:
            if score >= rerank_threshold:
                results.append(item)
        return results


if __name__ == "__main__":
    try:
        retriever = CodeRetriever(dataset_path="code.json")

        test_queries = [
            "使用A*算法，规划无人机从（0，0，0）起飞，向x轴正方向行进，在（10，0，0）附近有一个体积为10的正方体障碍，规划绕过障碍到达坐标（30，0，0）的路径",
            "Solve the 0/1 knapsack problem using dynamic programming",
            "Parse and extract email addresses",
            "Calculate the weighted average of a list",
            "Implement a simple HTTP server",
            "Implement a function that, given a dataset, carries out a basic convolutional neural network training workflow"
        ]

        print("\n" + "=" * 50)
        for q in test_queries:
            print(f"\n查询: {q}")
            results = retriever.search(q, top_k=1, recall_k=5, rerank_threshold=0.5)
            if results:
                print(f"返回代码: {results[0]['function_name']}")
            else:
                print("返回结果: None (降级为纯生成模式)")

    except FileNotFoundError:
        print("未找到 code.json 文件。")