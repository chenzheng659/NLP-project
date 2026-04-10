"""
app.py - Gradio 前端界面
双模式代码生成/编辑助手，连接 FastAPI 后端 /generate 接口。
"""
import os

import requests
import gradio as gr

# 后端地址，可通过环境变量覆盖
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")


def generate_code(instruction: str, source_code: str):
    """调用后端 /generate 接口，返回各字段结果"""
    if not instruction.strip():
        return "⚠️ 请先输入自然语言指令", "", "", "", ""

    payload = {"instruction": instruction.strip()}
    if source_code and source_code.strip():
        payload["source_code"] = source_code.strip()

    try:
        resp = requests.post(
            f"{BACKEND_URL}/generate",
            json=payload,
            timeout=120,
        )
        resp.raise_for_status()
        result = resp.json()
    except requests.exceptions.ConnectionError:
        err = f"❌ 无法连接后端服务（{BACKEND_URL}），请先启动后端：\nuvicorn code.api:app --host 0.0.0.0 --port 8000"
        return err, "", "", "", ""
    except requests.exceptions.HTTPError as e:
        return f"❌ 后端返回错误：{e.response.status_code} {e.response.text}", "", "", "", ""
    except Exception as e:
        return f"❌ 请求失败：{e}", "", "", "", ""

    mode_label = {
        "retrieval_generation": "🔍 模式一：检索生成",
        "direct_edit": "✏️ 模式二：直接编辑",
    }.get(result.get("mode", ""), result.get("mode", ""))

    changed_label = "✅ 有修改" if result.get("changed") else "⬜ 无修改"
    summary = (
        f"{mode_label}\n"
        f"合并方式：{result.get('merge_method', '')}\n"
        f"修改状态：{changed_label}\n"
        f"修改说明：{result.get('patch_note', '')}"
    )

    retrieved = result.get("retrieved_code") or "（本次未命中检索，或为直接编辑模式）"
    before    = result.get("before_code", "")
    after     = result.get("after_code", "")
    diff      = result.get("diff", "（无差异）")

    return summary, retrieved, before, after, diff


# ── Gradio UI ─────────────────────────────────────────────────────────────────

with gr.Blocks(title="EfficientEdit 代码生成/编辑系统", theme=gr.themes.Soft()) as demo:

    gr.Markdown(
        """
# 🤖 EfficientEdit 代码生成 / 编辑系统
> 基于「检索 + 生成」的双模式代码助手（BGE-M3 向量检索 × DeepSeek 大模型 × AST 智能合并）

| 模式 | 触发条件 | 流程 |
|------|---------|------|
| **模式一：检索生成** | 仅填写自然语言指令 | 检索代码库 → LLM 修改 → AST 合并 |
| **模式二：直接编辑** | 同时填写指令 + 原始代码 | 直接以原始代码为草稿 → LLM 修改 → AST 合并 |
        """
    )

    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### 📝 输入")
            instruction_input = gr.Textbox(
                label="自然语言指令（必填）",
                placeholder="例如：计算一个列表的加权平均值",
                lines=3,
            )
            source_code_input = gr.Textbox(
                label="原始代码（可选）——填写后进入直接编辑模式",
                placeholder="将你的代码粘贴到这里...",
                lines=12,
            )
            submit_btn = gr.Button("🚀 生成 / 编辑代码", variant="primary")

        with gr.Column(scale=1):
            gr.Markdown("### 📊 运行摘要")
            summary_output = gr.Textbox(
                label="摘要",
                lines=5,
                interactive=False,
            )
            retrieved_output = gr.Textbox(
                label="检索到的基础草稿（模式一）",
                lines=8,
                interactive=False,
            )

    with gr.Row():
        before_output = gr.Code(
            label="修改前代码",
            language="python",
            lines=15,
            interactive=False,
        )
        after_output = gr.Code(
            label="修改后代码（最终输出）",
            language="python",
            lines=15,
            interactive=False,
        )

    diff_output = gr.Textbox(
        label="Unified Diff 对比",
        lines=10,
        interactive=False,
    )

    submit_btn.click(
        fn=generate_code,
        inputs=[instruction_input, source_code_input],
        outputs=[summary_output, retrieved_output, before_output, after_output, diff_output],
    )

    gr.Markdown(
        f"---\n⚙️ 当前后端地址：`{BACKEND_URL}`  "
        "（可通过环境变量 `BACKEND_URL` 修改）"
    )


if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False)
