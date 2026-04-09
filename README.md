# 基于 EfficientEdit 的「检索 + 生成」混合代码生成框架

# 一、项目简介

本项目是一个基于 EfficientEdit 核心思想构建的「检索 + 生成」混合代码生成与编辑框架。旨在解决大语言模型（LLM）从零生成代码时容易产生幻觉、上下文脱节或不符合本地项目规范等问题。核心思路是结合 RAG（检索增强生成）与 LLM 的代码编辑能力，在生成前从私有代码知识库中检索出可复用的“基础草稿”，再由 LLM 根据自然语言指令生成精确的代码补丁，最后通过 AST 级别智能融合，实现高效、可靠、规范的代码生成。

# 二、系统架构

```text
       [ 前端 (Gradio) ]
              │ (提供双输入框：自然语言需求、可选的原始代码)
              ▼
    [ 后端 API 层 (FastAPI) ]
              │ (暴露 /generate 接口接收请求)
              ▼
[ 工作流引擎 (workflow.py, 双模式路由) ]
              │
              ├──▶ [ 检索层 (BGE-M3 + FAISS) ] ──▶ [ 知识库 (code.json, 本地常用 Python 函数) ]
              │
              ▼
[ 大模型调用层 (llm_client.py, DeepSeek API) ]
              │ (根据模式套用 prompt，提取补丁，过滤 <think> 标签)
              ▼
[ 代码融合层 (patch_merger.py, AST 级合并) ]
              │ (智能融合函数/类，若解析失败兜底至文本覆盖)
              ▼
      [ 返回响应 JSON ]
```

# 三、双模式工作流说明

本项目支持两种代码处理模式，工作流引擎会根据用户是否传入 `source_code` 自动进行路由：

*   **模式一（检索生成模式）**：
    仅输入自然语言需求。系统首先使用向量检索器在本地 `code.json` 中召回最相关的代码片段作为“基础草稿”；随后构建检索生成专用 Prompt 引导 LLM 输出代码修改补丁；最后使用代码融合模块将草稿与补丁合并为最终输出。
*   **模式二（直接编辑模式）**：
    输入原始代码 + 编辑指令。系统跳过检索阶段，直接以用户提供的原始代码作为“基础草稿”；随后构建直接编辑专用 Prompt 让 LLM 针对性地输出修改补丁；最后通过代码融合模块将修改智能合并到原始代码中。

# 四、目录结构

```text
/
├── project/
│   ├── code.json                 # 私有代码知识库（包含数十个 Python 工具函数与算法）
│   ├── retriever_and_schemas.py  # 检索器底层实现（基于 BGE-M3 向量化 + FAISS 索引双阶检索）
│   ├── prompt_templates.txt      # 双模式的系统提示词模板库
│   └── requirements.txt          # 核心底层依赖库声明
├── code/
│   ├── api.py                    # FastAPI 服务入口，暴露核心的 /generate 接口
│   ├── workflow.py               # 核心工作流引擎，负责串联检索、调用与合并模块
│   ├── llm_client.py             # 大模型调用与响应解析（含重试、容错、<think>过滤等）
│   ├── patch_merger.py           # 代码融合模块（基于 libcst 的 AST 级智能合并 + 文本兜底）
│   ├── retriever.py              # 检索器适配层（对底层 retriever 模块进行单例封装）
│   └── config.py                 # 全局配置文件（API Key、路径、模型超时与阈值等）
├── docs/
│   └── member_c_report.md        # 成员C模块（模型调用与代码融合）的详细技术与重构文档
├── tests/
│   ├── test_llm_client.py        # 针对大模型返回内容的解析逻辑及容错重试的单元测试
│   └── test_patch_merger.py      # 针对 AST 智能合并与各种异常边界的合并逻辑测试
└── README.md                     # 项目全局介绍文档（本文档）
```

# 五、快速启动

## 1. 环境安装
确保本地已安装 Python 3.8+，然后在项目根目录下执行：
```bash
pip install -r project/requirements.txt
```

## 2. 配置
运行前，请打开 `code/config.py`，根据实际情况修改配置参数：
*   **`DEEPSEEK_API_KEY`**: 填入你自己的 DeepSeek API 密钥。
*   **`LLM_TIMEOUT`**: 大模型请求超时时间（默认 60.0 秒）。
*   **`RECALL_K`**: FAISS 第一阶段向量召回的数量（默认 5）。
*   **`RERANK_THRESHOLD`**: 交叉编码器重排的及格分数阈值，低于此值将放弃草稿进入纯生成模式（默认 0.0）。

## 3. 启动服务
在项目根目录下，使用 `uvicorn` 启动 FastAPI 后端服务：
```bash
uvicorn code.api:app --host 0.0.0.0 --port 8000 --reload
```

## 4. 接口调用示例

### 示例 A：模式一（仅自然语言）
```bash
curl -X POST "http://127.0.0.0:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{
           "instruction": "计算一个列表的加权平均值"
         }'
```
**预期返回 JSON 结构**：
```json
{
  "mode": "retrieval_generation",
  "retrieved_code": "def average(values):\n    return sum(values) / len(values)",
  "before_code": "def average(values):\n    return sum(values) / len(values)",
  "after_code": "def weighted_average(values, weights):\n    return sum(v * w for v, w in zip(values, weights)) / sum(weights)",
  "diff": "--- before/code.py\n+++ after/code.py\n...",
  "changed": true,
  "patch_note": "修改为计算加权平均值，增加了 weights 参数",
  "merge_method": "ast"
}
```

### 示例 B：模式二（原始代码 + 编辑指令）
```bash
curl -X POST "http://127.0.0.0:8000/generate" \
     -H "Content-Type: application/json" \
     -d '{
           "instruction": "给这个函数加上类型提示",
           "source_code": "def add(a, b):\n    return a + b"
         }'
```
**预期返回 JSON 结构**：
```json
{
  "mode": "direct_edit",
  "retrieved_code": null,
  "before_code": "def add(a, b):\n    return a + b",
  "after_code": "def add(a: int, b: int) -> int:\n    return a + b",
  "diff": "--- before/code.py\n+++ after/code.py\n...",
  "changed": true,
  "patch_note": "增加了基于 int 类型的 Type Hints",
  "merge_method": "ast"
}
```

# 六、小组成员与分工

| 成员 | 负责模块 | 核心文件 |
|------|----------|----------|
| 陈峥 | 检索系统 + 架构设计 | `retriever_and_schemas.py`, `retriever.py` |
| 张明钰 | 数据集 + 提示词 | `code.json`, `prompt_templates.txt` |
| 覃钰源 | 模型调用 + 代码融合 | `llm_client.py`, `patch_merger.py` |
| 胡博雄 | 后端服务 + 工作流引擎 | `api.py`, `workflow.py` |
| 梁辰飞 | 前端界面 + 测试演示 | gradio 前端, `tests/` |

# 七、各模块文档索引

*   📄 **[成员qyy 技术报告：模型调用与代码融合重构](docs/member_qyy_report.md)** 
    （详细记录了 `llm_client.py` 和 `patch_merger.py` 的重构设计、AST 合并策略、接口契约及边缘踩坑记录）
*   *(等待其他成员更新他们的专属模块文档...)*
