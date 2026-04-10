"""
frontend/app.py - Gradio 前端界面
向本地 FastAPI 后端 http://127.0.0.1:8000/generate 发送请求，并展示结果。
"""

import requests
import gradio as gr

BACKEND_URL = "http://127.0.0.1:8000/generate"


def generate(instruction: str, source_code: str):
    """向后端发送请求并返回格式化的各字段结果。"""
    if not instruction.strip():
        return (
            "",  # mode
            "⚠️ 请填写自然语言指令后再提交。",  # patch_note
            gr.update(visible=False),  # retrieved_code_row
            "",  # retrieved_code
            "",  # before_code
            "",  # after_code
            "",  # diff
        )

    payload = {"instruction": instruction.strip()}
    if source_code and source_code.strip():
        payload["source_code"] = source_code.strip()

    try:
        resp = requests.post(BACKEND_URL, json=payload, timeout=60)
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        msg = (
            "❌ 无法连接到后端服务。\n"
            "请先在终端中启动后端：\n\n"
            "    uvicorn code.api:app --host 0.0.0.0 --port 8000 --reload"
        )
        return ("", msg, gr.update(visible=False), "", "", "", "")
    except requests.exceptions.Timeout:
        return ("", "❌ 请求超时，请稍后重试。", gr.update(visible=False), "", "", "", "")
    except requests.exceptions.HTTPError as e:
        detail = ""
        error_response = e.response
        try:
            detail = error_response.json().get("detail", "")
        except Exception:
            pass
        return ("", f"❌ 后端返回错误 {error_response.status_code}：{detail or str(e)}", gr.update(visible=False), "", "", "", "")
    except Exception as e:
        return ("", f"❌ 未知错误：{e}", gr.update(visible=False), "", "", "", "")

    data = resp.json()
    mode = data.get("mode", "")
    patch_note = data.get("patch_note", "")
    retrieved_code = data.get("retrieved_code") or ""
    before_code = data.get("before_code", "")
    after_code = data.get("after_code", "")
    diff = data.get("diff", "")

    # 仅在模式一（retrieval_generation）时显示检索到的基础草稿
    show_retrieved = mode == "retrieval_generation" and bool(retrieved_code)

    return (
        mode,
        patch_note,
        gr.update(visible=show_retrieved),
        retrieved_code,
        before_code,
        after_code,
        diff,
    )


# ── 界面构建 ───────────────────────────────────────

with gr.Blocks(title="EfficientEdit 代码生成/编辑系统") as demo:
    gr.Markdown(
        """
        # 🛠️ EfficientEdit 代码生成 / 编辑系统
        基于「检索 + 生成」混合工作流，支持两种模式：
        - **模式一（检索生成）**：仅填写自然语言指令，系统自动检索最匹配的代码草稿，再按指令修改。
        - **模式二（直接编辑）**：同时提供原始代码与编辑指令，系统直接对代码进行修改。
        """
    )

    with gr.Row():
        with gr.Column():
            instruction_input = gr.Textbox(
                label="自然语言指令（必填）",
                placeholder="例如：计算一个列表的加权平均值",
                lines=3,
            )
            source_code_input = gr.Code(
                label="原始代码（可选，留空则进入模式一）",
                language="python",
                lines=10,
            )
            submit_btn = gr.Button("🚀 提交", variant="primary")

        with gr.Column():
            mode_output = gr.Textbox(label="当前模式 (mode)", interactive=False)
            patch_note_output = gr.Textbox(
                label="补丁说明 (patch_note)", interactive=False, lines=3
            )

            # 仅模式一显示
            retrieved_code_row = gr.Column(visible=False)
            with retrieved_code_row:
                retrieved_code_output = gr.Code(
                    label="检索到的基础草稿 (retrieved_code，模式一)",
                    language="python",
                    lines=8,
                    interactive=False,
                )

            before_code_output = gr.Code(
                label="修改前的代码 (before_code)",
                language="python",
                lines=10,
                interactive=False,
            )
            after_code_output = gr.Code(
                label="修改后的最终代码 (after_code)",
                language="python",
                lines=10,
                interactive=False,
            )
            diff_output = gr.Textbox(
                label="代码差异 (diff)",
                lines=12,
                interactive=False,
            )

    submit_btn.click(
        fn=generate,
        inputs=[instruction_input, source_code_input],
        outputs=[
            mode_output,
            patch_note_output,
            retrieved_code_row,
            retrieved_code_output,
            before_code_output,
            after_code_output,
            diff_output,
        ],
    )

if __name__ == "__main__":
    demo.launch(share=False)
