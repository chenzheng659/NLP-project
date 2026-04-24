import asyncio
import sys
import json
from unittest.mock import MagicMock

# Mock heavy modules before any imports
sys.modules['torch'] = MagicMock()
sys.modules['faiss'] = MagicMock()
sys.modules['sentence_transformers'] = MagicMock()
sys.modules['numpy'] = MagicMock()

sys.path.append('src')
sys.path.append('project')

import workflow

# Mock search_code to return expected snippets without needing PyTorch/FAISS
def mock_search_code(instruction):
    if "加权平均值" in instruction:
        return "def average(values):\n    return sum(values) / len(values)"
    elif "JSON" in instruction:
        return "def get_current_timestamp(format_str='%Y-%m-%d %H:%M:%S'):\n    import datetime\n    return datetime.datetime.now().strftime(format_str)"
    return ""

workflow.search_code = mock_search_code

async def test_case(name, instruction, source_code=None):
    print(f"\n=== {name} ===")
    try:
        res = await workflow.run_workflow(instruction, source_code)
        # remove llm_raw from print to keep it clean, or keep it.
        if "llm_raw" in res:
            res["llm_raw"] = "...[hidden]..."
        print(json.dumps(res, ensure_ascii=False, indent=2))
        return res
    except Exception as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
        return {"error": str(e)}

async def main():
    await test_case("Case 1 (Mode 1, High Reuse)", "计算一个列表的加权平均值，权重由另一个列表提供")
    await test_case("Case 2 (Mode 1, Low Reuse)", "解析一个 JSON 文件并提取其中所有的键名")
    await test_case("Case 3 (Mode 2, Local Mod)", "给这个函数添加一个 reverse 参数，控制升序还是降序排列", "def sort_list(lst):\n    return sorted(lst)")
    await test_case("Case 4 (Mode 2, No Mod)", "这个函数已经很好了，不需要任何修改", "def add(a, b):\n    return a + b")
    await test_case("Case 5 (Empty Instruction)", "", None)
    await test_case("Case 6 (Invalid Python fallback)", "修复代码", "def bad_syntax(a, b:\n    return a+b\n!!!")

if __name__ == "__main__":
    asyncio.run(main())
