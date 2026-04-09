# 一、工作概述

本次工作主要负责代码生成与编辑后端系统中的两个核心模块：**模型调用层（`llm_client.py`）**与**代码融合层（`patch_merger.py`）**的重构与升级。

在此次重构之前，基础代码已经具备了调用大语言模型（LLM）和生成简单文本对比（Diff）的能力，但在异常处理、数据流转类型安全、模型行为的边缘场景适配等方面存在隐患。本次工作的核心目标是：
1. **健壮性增强**：引入 API 调用重试机制、处理带推理过程模型的 `<think>` 标签干扰，并利用 AST（抽象语法树）实现更精确、可靠的代码合并。
2. **接口统一与类型安全**：全面使用 Python `dataclass` 构建结构化的内部数据流对象（`ParsedResponse` 和 `MergeResult`），消除松散 `dict` 带来的键名维护风险。
3. **联调打通与测试覆盖**：与上下游的 `workflow.py`（工作流层）和 `api.py`（接口层）完成无缝对接，并将最新的底层合并状态透传给前端，最后编写覆盖核心场景和边界条件的自动化测试用例，确保系统高度可用。

---

# 二、核心设计思想

## 2.1 模型调用层（`llm_client.py`）

- **结构化输出响应（ParsedResponse dataclass）**：
  引入 `dataclass`，强类型化了 LLM 返回解析后的数据。明确定义 `original_code`、`modified_code`、`explanation` 和 `modified` 布尔标志，避免字典取值时易犯的 Key 拼写错误，大大降低了与上游 `workflow.py` 联调的认知负担。
- **双模式 Prompt 动态路由**：
  基于布尔参数 `has_source_code`，代码能够智能选择项目内置的 `retrieval_mode_zh` 或 `direct_edit_mode_zh` 模板，消除了原先代码中的硬编码实现。
- **解决“无修改”逻辑冲突的根因**：
  原版实现中，模板提示词让模型在无需修改时输出“无修改”，导致基于正则查找 `### 修改前` 和 `### 修改后` 的解析器发生崩溃或错乱。修复思路是双管齐下：在提示词中强调哪怕无需修改，也要输出完整三段式（并在说明中填入“无需修改”）；在解析代码中增加 `no_change_keywords` 短路检测，一旦命中直接返回原代码，强制标定 `modified=False`，阻止正则进入死胡同。
- **`<think>` 标签的防御性剥离**：
  考虑到项目使用的是 DeepSeek 等带有强大推理思考能力的模型（如 DeepSeek R1），模型输出内容开头往往伴随着大段被 `<think>...</think>` 包裹的内部思维链。这些内容可能包含干扰性代码块。通过在解析伊始加入 `re.sub(..., flags=re.DOTALL)` 全局移除，保障了解析引擎的纯净。
- **重试与容错机制**：
  LLM API 调用受制于网络与并发配额，偶尔会发生超时或 5xx 错误。引入了 `httpx.AsyncClient` 的配置化超时支持，并结合 asyncio 写了一套轻量级的 `Max Retries` 机制（默认2次重试），提高了接口稳定性。

## 2.2 代码融合层（`patch_merger.py`）

- **为什么选择 `libcst` 引入 AST 级别合并**：
  原本的合并策略是直接将 LLM 输出的内容替换掉文件内容。但在长代码或大文件中，模型往往只会返回“发生修改的那个函数”，这会导致丢失上下文其它未修改的代码。使用 `libcst` 可以在 Python 语法树层面对比，精准定位并替换修改的函数或类节点，保留原文件中与修改无关的其他部分。
- **AST 合并与 Fallback 机制的设计**：
  模型生成的代码并不总是完美的（可能缺括号、语法错乱）。设计 `smart_merge` 的核心思路是：“尽可能高级，必须安全”。首先尝试基于 AST 解析与融合，如果发生任何 `cst.ParserSyntaxError` 或融合失败，拦截异常，静默降级（Fallback）回传统的全量文本覆盖模式（`text`）。
- **`MergeResult` 数据流封装**：
  与模型调用层呼应，封装了 `MergeResult` 数据类，确保返回包括合成代码、Diff 文本、甚至内部合并算法决策痕迹（`merge_method: str`）的所有必要字段，方便日志排查及前端展示提示。

---

# 三、工作内容与改动清单

## `llm_client.py`
- **改动1**：引入 `dataclass ParsedResponse`，重构了 `parse_llm_response` 返回值，消除字典松散定义。
- **改动2**：调整 `build_prompt` 入参，支持 `has_source_code` 动态选择模板。修改并规范化了附加的格式要求，缓解了“无修改”响应乱码问题。
- **改动3**：重写 `call_llm`，添加网络级 `httpx.HTTPError` 和超时异常捕获，实现了 2 次退避重试逻辑。
- **改动4**：在 `parse_llm_response` 中加入正则前置处理器，强制抹除 `<think>` 推理内容；添加了基于关键字的“短路无修改”判定兜底功能。
- **改动5**：为文件加载逻辑 `_load_templates()` 添加 `try...except`，并抛出带详细路径说明的友好型异常。

## `patch_merger.py`
- **改动1**：引入并封装 `libcst`，编写了核心 AST 树遍历修改类 `ASTMerger(cst.CSTTransformer)`。
- **改动2**：新增 `merge_with_ast`，实现替换旧函数/类与追加新函数/类的合并逻辑，内置 SyntaxError 熔断。
- **改动3**：设计对外唯一暴露接口 `smart_merge` 及关联数据结构 `MergeResult`。处理了全新生成模式（base_code 为空）以及前后代码字面量相同的边界短路情况。

## `workflow.py`（联调修改）
- 更改内部调用的属性解构方式，兼容 `llm_client` 返回的 `ParsedResponse` 对象与 `patch_merger` 返回的 `MergeResult` 对象。
- 修改合并状态标识，采用 `changed = merge_result.modified and parsed.modified`，综合了大语言模型语言意图和最终文本 AST 对比情况，保证严谨。
- 向 API 返回的字典中追加了 `"merge_method": merge_result.merge_method`。

## `api.py`（联调修改）
- 在 `GenerateResponse` 数据校验 Schema (Pydantic) 中，新注册并要求输出 `merge_method: str` 字段。
- 修改了路由实现，从 workflow 接管结果后填充此新字段。

## `project/requirements.txt`
- 新增 AST 解析基础库：`libcst`。

## `tests/test_llm_client.py`（新建）
- `test_parse_normal`：测试带有 `<think>` 标签的正常三段式输出是否被正确解析并剥离思维链。
- `test_parse_no_change`：测试模型直接表达“不需要修改”时，短路逻辑是否生效。
- `test_parse_single_block`：测试仅单代码块兜底逻辑。
- `test_call_llm_retry`：使用 `@patch` 拦截 `httpx.post` 行为，模拟抛出 Timeout 后自动重试 1 次最终成功的完整网络恢复表现。

## `tests/test_patch_merger.py`（新建）
- `test_ast_merge_normal`：验证合并算法能将 patch 中新修改的方法更新，同时不丢失 base 中其余无关方法。
- `test_ast_merge_fallback`：注入错误的 Python 语法作为 patch 代码，验证安全降级退回到 `text` 替换模式不崩溃。
- `test_base_code_empty`：模拟从零生成的业务场景，退回 `text` 并直接生成代码。
- `test_same_code`：模拟补丁未改变原有内容时的空 Diff 效果，及 `modified=False` 判定。

---

# 四、对外接口说明（供其他成员使用）

## 4.1 `llm_client.py` 接口

### `build_prompt()`
**函数签名**：`def build_prompt(instruction: str, base_code: str, has_source_code: bool) -> str:`
**参数说明**：
- `instruction`: 用户输入的自然语言指令。
- `base_code`: 参与处理的代码内容（无源码时为检索出的原始草稿，有源码时为用户贴进来的全量源码）。
- `has_source_code`: 用于自动路由 prompt，True 将使用 `direct_edit_mode` 模板，False 使用 `retrieval_mode`。

### `call_llm()`
**函数签名**：`async def call_llm(prompt: str) -> str:`
**参数说明**：
- `prompt`: `build_prompt` 返回的拼接完整的大模型提示词。
**返回值**：LLM 原始的响应字符串。
**异常与容错**：自带 2 次重试，若超限或发生不可恢复的错误，会直接引发 `RuntimeError`，请上游按需捕捉。

### `parse_llm_response()`
**函数签名**：`def parse_llm_response(raw: str, base_code: str) -> ParsedResponse:`
**返回值（ParsedResponse）**：
- `original_code (str)`: LLM 提取的修改前代码。
- `modified_code (str)`: LLM 提取的修改后代码或补丁。
- `explanation (str)`: 对此次更改的说明内容。
- `modified (bool)`: 是否发生了实际修改的判别标识。

## 4.2 `patch_merger.py` 接口

### `smart_merge()`
**函数签名**：`def smart_merge(base_code: str, patch_code: str, use_ast: bool = True) -> MergeResult:`
**参数说明**：
- `base_code`: 最初步的参照物草稿代码。
- `patch_code`: 上一步 LLM 给出的补丁结果（`ParsedResponse.modified_code`）。
- `use_ast`: 允许开启 AST 合并算法（默认 True 开启，建议保留默认）。
**返回值（MergeResult）**：
- `final_code (str)`: 综合后的最终代码字符串。
- `unified_diff (str)`: 用于给前端库渲染的标准的 Unified Diff 字符串。
- `merge_method (str)`: 字符串 `"ast"` 或 `"text"`，记录最终算法实际使用了哪种机制融合。
- `modified (bool)`: 综合判定，最终合并后文本内容是否真的产生了变化。

---

# 五、数据流说明

```text
       [前端请求 / API入口]
               │
          [api.py] GenerateRequest
               │
               ▼
[workflow.py] detect_mode()
               │
               ├── (有 source_code) ─▶ 模式二
               └── (无 source_code) ─▶ 模式一 ──▶ [retriever.py]
               │
               ▼
        [llm_client.py]
          ├─ build_prompt()
          ├─ call_llm()
          └─ parse_llm_response()
               │
               ▼ 返回 ParsedResponse (original_code, modified_code)
               │
[workflow.py] 收到结果，透传属性给融合模块
               │
               ▼
       [patch_merger.py] smart_merge()
               │ 尝试 libcst 解析... (成功则 AST，失败则 Text)
               │
               ▼ 返回 MergeResult (final_code, unified_diff, merge_method)
               │
[workflow.py] 整合 changed 状态 = merge_result.modified AND parsed.modified
               │
          [api.py] 封装至 GenerateResponse
               │
       [返回 JSON 给前端渲染]
```

核心结构：整个调用链基于两级 Dataclass 对象传递控制权。`llm_client.py` 负责与不可靠的外部自然语言环境博弈并输出可靠的 `ParsedResponse`，而 `patch_merger.py` 扮演把门人，负责处理确定性规则，产出给呈现层的 `MergeResult` 记录状态。两者在 `workflow.py` 引擎层交汇整合。

---

# 六、注意事项 / 踩坑记录

- **DeepSeek R1 的 `<think>` 标签问题**：在带有 reasoning 的模型中，常常内部思路会先行输出。之前如果不做剔除，正则表达式会被推理过程中的举例代码直接干扰，截取出错误的代码段落。方案是务必在处理前通过正则 `re.sub` 进行阻断。
- **“无修改”与 Prompt 模板的逻辑冲突**：LLM 有时候遵循指令太好，只丢下一句“无需修改”导致后文的 Block 提取完全扑空。应对这类情况要在最前面加入自然语言关键字短路。
- **AST 降级时的属性遗漏 Bug（已在联调中修复）**：开发中途发现，当 `libcst` 解析失败跑进 `except` 代码块做全覆盖时，并未记录更新 `merge_method = "text"`（原先保留在外面）。虽然结果不影响，但是会导致前端 UI 展示了错误的 `"ast"` 方法，这会导致排障困难，已做纠正。
- **文件尾部的空白处理**：无论是 Diff 生成还是最终比对，不要忽略 Python 代码缩进和换行符 `.strip()` 隐藏的细节差异。在设计 AST 降级判断与 `is_modified` 判断时，做 strip() 校对才能保证空 Diff 状态判断的准确性。