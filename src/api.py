"""
api.py - FastAPI 入口
暴露 /generate 端点，接收请求并调用工作流引擎。
"""
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.retriever import get_retriever
from src.workflow  import run_workflow

class GenerateRequest(BaseModel):
    instruction: str = Field(..., description="自然语言需求或编辑指令")
    source_code: Optional[str] = Field(None)

class GenerateResponse(BaseModel):
    mode:           str            
    retrieved_code: Optional[str]  
    before_code:    str            
    after_code:     str            
    diff:           str            
    changed:        bool           
    patch_note:     str            
    merge_method:   str            

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("预热检索模型...")
    get_retriever()
    print("服务就绪，等待请求。")
    yield
    print("服务关闭。")

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest):
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
        merge_method=result["merge_method"],
    )

@app.get("/health")
async def health():
    return {"status": "ok"}
