import sys
import os
import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock
import httpx

# 将项目根目录加入 PYTHONPATH，使得测试能够通过包路径引入模块
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from code.llm_client import parse_llm_response, call_llm, ParsedResponse

def test_parse_normal():
    raw_response = """<think>推理过程...</think>
### 修改前
```python
def foo():
    return 1
```

### 修改后
```python
def foo():
    return 2
```

### 修改说明
改了返回值
"""
    base_code = "def foo():\n    return 1"
    res = parse_llm_response(raw_response, base_code)
    
    assert isinstance(res, ParsedResponse)
    assert res.original_code == "def foo():\n    return 1"
    assert res.modified_code == "def foo():\n    return 2"
    assert res.explanation == "改了返回值"
    assert res.modified is True


def test_parse_no_change():
    raw_response = "<think>不需要改什么</think>\n这里无需修改，代码很完美。"
    base_code = "def foo():\n    return 1"
    res = parse_llm_response(raw_response, base_code)
    
    assert res.modified is False
    assert res.original_code == base_code
    assert res.modified_code == base_code
    assert res.explanation == "无需修改"


def test_parse_single_block():
    raw_response = """<think>直接给出代码</think>
```python
def foo():
    return 10
```
"""
    base_code = "def foo():\n    return 1"
    res = parse_llm_response(raw_response, base_code)
    
    assert res.modified is True
    assert res.modified_code == "def foo():\n    return 10"


@pytest.mark.asyncio
@patch('code.llm_client.httpx.AsyncClient.post', new_callable=AsyncMock)
@patch('code.llm_client.asyncio.sleep', new_callable=AsyncMock)
async def test_call_llm_retry(mock_sleep, mock_post):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"choices": [{"message": {"content": "success_output"}}]}
    
    # 第一次报错（超时），第二次成功
    mock_post.side_effect = [
        httpx.ReadTimeout("Timeout error"),
        mock_response
    ]
    
    result = await call_llm("test prompt")
    
    assert result == "success_output"
    assert mock_post.call_count == 2
    mock_sleep.assert_called_once_with(1.0)
