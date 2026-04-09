"""
api.py - FastAPI 入口
暴露 /generate 端点，接收请求并调用工作流引擎。
"""
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"  # 修复 Windows OpenMP 冲突

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from retriever import get_retriever
from workflow  import run_workflow


# ── 请求 / 响应 Schema ─────────────────────────────

class GenerateRequest(BaseModel):
    instruction: str = Field(..., description="自然语言需求或编辑指令")
    source_code: Optional[str] = Field(
        None,
        description="待编辑的原始代码（可选）。有值→模式二直接编辑；为空→模式一检索生成"
    )


class GenerateResponse(BaseModel):
    mode:           str            = Field(..., description="使用的模式：retrieval_generation / direct_edit")
    retrieved_code: Optional[str]  = Field(None, description="模式一检索到的基础草稿")
    before_code:    str            = Field(..., description="修改前的代码")
    after_code:     str            = Field(..., description="修改后的代码（最终输出）")
    diff:           str            = Field(..., description="unified diff 格式的修改前后对比")
    changed:        bool           = Field(..., description="是否有实际修改")
    patch_note:     str            = Field(..., description="修改说明")


# ── 应用生命周期 ───────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时预热检索模型（避免第一次请求超时）
    print("预热检索模型...")
    get_retriever()
    print("服务就绪，等待请求。")
    yield
    print("服务关闭。")


# ── FastAPI 实例 ───────────────────────────────────

app = FastAPI(
    title="EfficientEdit 后端服务",
    description="双模式代码生成/编辑 API（检索生成 & 直接编辑）",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # 生产环境改为前端实际地址
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 端点 ───────────────────────────────────────────

@app.post("/generate", response_model=GenerateResponse, summary="代码生成/编辑主接口")
async def generate(req: GenerateRequest):
    """
    双模式代码生成接口：

    - 仅提供 `instruction` → 模式一：在代码库中检索最匹配的代码，再按指令修改
    - 同时提供 `source_code` + `instruction` → 模式二：直接对提供的代码按指令修改

    响应包含修改前后代码及 unified diff 对比。
    """
    try:
        result = await run_workflow(req.instruction, req.source_code)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return GenerateResponse(
        mode=result["mode"],
        retrieved_code=result["retrieved_code"],
        before_code=result["before_code"],
        after_code=result["after_code"],
        diff=result["diff"],
        changed=result["changed"],
        patch_note=result["patch_note"],
    )


@app.get("/health", summary="健康检查")
async def health():
    return {"status": "ok"}
