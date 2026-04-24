import gradio as gr
import requests
import html

# ── Config ──────────────────────────────────────────
BACKEND_BASE = "http://127.0.0.1:8000"
GENERATE_URL = f"{BACKEND_BASE}/generate"

# ── API Call ────────────────────────────────────────
def process(source_code, instruction):
    if not instruction.strip():
        # Return updates for all outputs to avoid errors
        return "", "", "", "请填写「需求 / 指令」后再提交。", "", gr.update(visible=False, value="")

    try:
        payload = {"source_code": source_code or None, "instruction": instruction}
        resp = requests.post(GENERATE_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        base_draft = data.get("retrieved_code") or data.get("before_code", "")
        patch_code = data.get("diff", "")
        final_code = data.get("after_code", "")

        mode = "检索生成" if data.get("mode") == "retrieval_generation" else "直接编辑"
        status = "✅ 有修改" if data.get("changed") else "⬜ 无修改"
        log = (
            f"模式：{mode}\n"
            f"状态：{status}\n"
            f"说明：{data.get('patch_note', '')}\n"
            f"合并方式：{data.get('merge_method', '')}"
        )

        viz_html = ""
        viz_markdown = gr.update(visible=False, value="")
        if data.get("is_drone_related") and data.get("visualization_url"):
            viz_url = f"{BACKEND_BASE}{data['visualization_url']}"
            safe_url = html.escape(viz_url)
            # CRITICAL FIX: Use a Markdown component for a reliable link
            markdown_content = f"""
            <div style='padding: 10px; border: 1px solid #334155; border-radius: 10px; text-align: center;'>
                <span style='font-size: 1.2em;'>🚁</span>
                <a href='{safe_url}' target='_blank' style='color: #38bdf8; text-decoration: none; font-weight: bold; margin-left: 10px;'>
                    在新标签页中打开 3D 可视化
                </a>
            </div>
            """
            viz_markdown = gr.update(visible=True, value=markdown_content)
            viz_html = f'<iframe src="{safe_url}" width="100%" height="480" style="border:none;border-radius:10px;"></iframe>'

        return base_draft, patch_code, final_code, log, viz_html, viz_markdown
    except Exception as e:
        return "", "", "", f"后端请求失败：{e}", "", gr.update(visible=False, value="")

# ── UI Layout ───────────────────────────────────────
with gr.Blocks(css=".gradio-container {background: #0a0e17; color: #e2e8f0;}", title="EfficientEdit · 混合代码生成框架") as demo:
    gr.HTML("""
    <div style="text-align:center; padding:20px; background:linear-gradient(135deg, #0d1b2a, #1a2744); border-radius:15px; border: 1px solid #1e3a5f;">
        <h1 style="color:#e8f4ff; font-size:2rem; margin:0;">EfficientEdit · 混合代码生成框架</h1>
        <p style="color:#7aadcc; font-size:1rem;">基于「检索 + 生成」的双模式代码编辑系统</p>
    </div>
    """)

    with gr.Row():
        with gr.Column(scale=5):
            source_code = gr.Code(label="原始代码 (可选)", language="python", lines=12)
            instruction = gr.Textbox(label="需求 / 指令 (必填)", lines=5)
            btn_run = gr.Button("生成代码", variant="primary")
        with gr.Column(scale=7):
            with gr.Tabs():
                with gr.TabItem("最终代码"):
                    final_code = gr.Code(label="融合后的完整代码", language="python", lines=10)
                with gr.TabItem("生成补丁 (Diff)"):
                    patch_code = gr.Code(label="LLM 生成的修改/新增代码块 (Diff格式)", language="diff", lines=10)
                with gr.TabItem("基础草稿"):
                    base_draft = gr.Code(label="系统检索到/直接使用的基础草稿", language="python", lines=10)
            log_output = gr.Textbox(label="处理日志", lines=4, interactive=False)

    # Visualization Section
    viz_markdown_link = gr.Markdown(visible=False)
    drone_viz = gr.HTML(value="")

    btn_run.click(
        fn=process,
        inputs=[source_code, instruction],
        outputs=[base_draft, patch_code, final_code, log_output, drone_viz, viz_markdown_link],
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860)
