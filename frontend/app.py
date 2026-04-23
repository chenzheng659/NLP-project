import gradio as gr
import requests
import json

# ── 后端 API 地址（开发阶段可先用 Mock）──────────────────────────────
BACKEND_URL = "http://127.0.0.1:8000/generate"
BACKEND_BASE = "http://127.0.0.1:8000"
VISUALIZER_URL = f"{BACKEND_BASE}/visualizer"


# ── Mock 函数（后端未就绪时使用）────────────────────────────────────
def mock_generate(source_code, instruction):
    """临时 Mock，后端联调完成后删除此函数"""
    if source_code.strip():
        mode = "模式二（直接编辑模式）"
        draft = source_code
        patch = f"# [Mock 补丁]\n# 根据指令「{instruction}」生成的修改内容\ndef example_patch():\n    pass"
        result = source_code + "\n\n# --- 融合补丁 ---\n" + patch
    else:
        mode = "模式一（检索生成模式）"
        draft = f'# [Mock 检索结果]\n# 从私有代码库中检索到的最匹配函数\ndef retrieved_function(data):\n    """与需求最相近的历史代码"""\n    return data'
        patch = f"# [Mock 补丁]\n# 根据需求「{instruction}」生成的补丁\ndef patched_function(data, extra_param=None):\n    result = retrieved_function(data)\n    # 新增逻辑\n    return result"
        result = patch

    log = f""" 处理日志
──────────────────────────────
触发模式：{mode}
用户指令：{instruction}
状态：处理完成（Mock 模式）
──────────────────────────────"""
    return draft, patch, result, log


# ── 核心处理函数 ─────────────────────────────────────────────────────
def process(source_code, instruction, use_mock):
    if not instruction.strip():
        return "", "", "", "请填写「需求 / 指令」后再提交。", ""

    if use_mock:
        draft, patch, result, log = mock_generate(source_code, instruction)
        return draft, patch, result, log, ""

    # 调用真实后端
    try:
        payload = {
            "source_code": source_code if source_code.strip() else None,
            "instruction": instruction,
        }
        resp = requests.post(BACKEND_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        # 映射后端响应字段到前端输出
        # base_draft：模式一用检索到的草稿，模式二用修改前的原始代码
        base_draft = data.get("retrieved_code") or data.get("before_code", "")

        # patch_code：展示 unified diff，直观呈现 LLM 所做的修改
        patch_code = data.get("diff", "")

        # final_code：融合后的最终代码
        final_code = data.get("after_code", "")

        # 构造日志
        mode_label = (
            "模式一（检索生成模式）"
            if data.get("mode") == "retrieval_generation"
            else "模式二（直接编辑模式）"
        )
        changed_text = "✅ 有修改" if data.get("changed") else "⬜ 无修改"
        log = (
            f" 处理日志\n"
            f"──────────────────────────────\n"
            f"触发模式：{mode_label}\n"
            f"用户指令：{instruction}\n"
            f"修改状态：{changed_text}\n"
            f"修改说明：{data.get('patch_note', '')}\n"
            f"合并方式：{data.get('merge_method', '')}\n"
            f"──────────────────────────────"
        )

        # 无人机可视化 iframe（当后端检测到无人机相关代码时）
        viz_html = ""
        if data.get("is_drone_related") and data.get("visualization_url"):
            viz_url = f"{BACKEND_BASE}{data['visualization_url']}"
            import html as _html
            safe_url = _html.escape(viz_url)
            viz_html = f"""
<div style="margin-top:16px;background:linear-gradient(135deg,#0d1b2a,#0f2027);
            border:1px solid #1e3a5f;border-radius:14px;padding:16px 20px;">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;">
        <span style="font-size:1.3rem;">🚁</span>
        <span style="color:#4cc9f0;font-size:0.95rem;font-weight:700;letter-spacing:1px;">
            已生成无人机路径 3D 可视化
        </span>
        <a href="{safe_url}" target="_blank"
           style="margin-left:auto;padding:6px 14px;background:linear-gradient(135deg,#1d4ed8,#0891b2);
                  color:#fff;border-radius:6px;font-size:0.8rem;font-weight:600;text-decoration:none;">
            🔗 新标签页打开
        </a>
    </div>
    <iframe src="{safe_url}" width="100%" height="480"
            style="border:none;border-radius:10px;background:#1a1a2e;"
            allowfullscreen></iframe>
</div>"""

        return base_draft, patch_code, final_code, log, viz_html
    except Exception as e:
        return (
            "",
            "",
            "",
            f" 后端请求失败：{e}\n\n 提示：可勾选「使用 Mock 模式」在本地测试前端。",
            "",
        )


def check_drone_status():
    """检查后端无人机可视化模块是否可用"""
    import html as _html
    safe_url = _html.escape(VISUALIZER_URL)
    try:
        resp = requests.get(f"{BACKEND_BASE}/health", timeout=3)
        if resp.status_code != 200:
            return "❌ 后端服务未响应"
        # 用 HEAD 请求检测 visualizer 端点，减少传输开销
        viz_resp = requests.head(VISUALIZER_URL, timeout=5)
        if viz_resp.status_code == 200:
            return f"✅ 无人机可视化模块在线 → <a href='{safe_url}' target='_blank'>{safe_url}</a>"
        elif viz_resp.status_code == 503:
            return "⚠️ 后端在线，但无人机可视化模块加载失败（查看后端终端日志获取详情）"
        else:
            return f"⚠️ 后端返回异常状态码 {viz_resp.status_code}"
    except Exception as e:
        return f"❌ 无法连接后端：{e}"


def clear_all():
    return "", "", "", "", "", "", ""


# ── 自定义 CSS ────────────────────────────────────────────────────────
CSS = """
/* ── 字体 ── */
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;800&family=JetBrains+Mono:wght@400;500&display=swap');

body, .gradio-container {
    font-family: 'Syne', sans-serif !important;
    background: #0a0e17 !important;
}

/* ── 顶部标题区 ── */
#header-box {
    background: linear-gradient(135deg, #0d1b2a 0%, #1a2744 50%, #0f2027 100%);
    border: 1px solid #1e3a5f;
    border-radius: 16px;
    padding: 36px 40px 28px;
    margin-bottom: 24px;
    position: relative;
    overflow: hidden;
}
#header-box::before {
    content: '';
    position: absolute;
    top: -60px; right: -60px;
    width: 200px; height: 200px;
    background: radial-gradient(circle, rgba(0,180,255,0.12) 0%, transparent 70%);
    pointer-events: none;
}
#header-box h1 {
    font-size: 1.9rem !important;
    font-weight: 800 !important;
    color: #e8f4ff !important;
    margin: 0 0 6px !important;
    letter-spacing: -0.5px;
}
#header-box p {
    color: #7aadcc !important;
    font-size: 0.92rem !important;
    margin: 0 !important;
}

/* ── 模式徽标 ── */
.mode-badge {
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 3px 10px;
    border-radius: 20px;
    margin-right: 8px;
}
.badge-m1 { background: #0d3349; color: #38bdf8; border: 1px solid #0ea5e9; }
.badge-m2 { background: #1a2e1a; color: #4ade80; border: 1px solid #22c55e; }

/* ── 分区标签 ── */
.section-label {
    font-size: 1.1rem !important;
    font-weight: 600 !important;
    letter-spacing: 1.5px !important;
    text-transform: uppercase !important;
    color: #4a8fa8 !important;
    margin-bottom: 8px !important;
}

/* ── 输入面板 ── */
#input-panel {
    background: #0d1420 !important;
    border: 1px solid #1c3050 !important;
    border-radius: 14px !important;
    padding: 24px !important;
}

/* ── 输出面板 ── */
#output-panel {
    background: #090e18 !important;
    border: 1px solid #1c3050 !important;
    border-radius: 14px !important;
    padding: 24px !important;
}

/* ── Textbox 样式 ── */
.gr-textbox textarea, .gr-code textarea {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.82rem !important;
    background: #060b13 !important;
    border: 1px solid #1e3555 !important;
    border-radius: 10px !important;
    color: #c8dff0 !important;
    line-height: 1.6 !important;
}
.gr-textbox textarea:focus {
    border-color: #2563eb !important;
    box-shadow: 0 0 0 2px rgba(37,99,235,0.2) !important;
}

/* ── 按钮 ── */
#btn-run {
    background: linear-gradient(135deg, #1d4ed8, #0891b2) !important;
    border: none !important;
    border-radius: 10px !important;
    color: #fff !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
    letter-spacing: 0.5px !important;
    padding: 12px !important;
    transition: all 0.2s ease !important;
}
#btn-run:hover {
    transform: translateY(-1px) !important;
    box-shadow: 0 6px 20px rgba(8,145,178,0.4) !important;
}
#btn-clear {
    background: #0d1420 !important;
    border: 1px solid #1e3555 !important;
    border-radius: 10px !important;
    color: #7aadcc !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 600 !important;
    transition: all 0.2s ease !important;
}
#btn-clear:hover {
    border-color: #38bdf8 !important;
    color: #38bdf8 !important;
}

/* ── 日志框 ── */
#log-box textarea {
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.78rem !important;
    background: #060b13 !important;
    color: #52a884 !important;
    border: 1px solid #163325 !important;
    border-radius: 10px !important;
}

/* ── Accordion ── */
.gr-accordion {
    background: #0b1220 !important;
    border: 1px solid #1c3050 !important;
    border-radius: 10px !important;
}

/* ── Label 颜色 ── */
label span, .gr-form label {
    color: #a8c4dc !important;
    font-family: 'Syne', sans-serif !important;
    font-size: 0.85rem !important;
}

/* ── 分隔线 ── */
.divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, #1e3a5f, transparent);
    margin: 20px 0;
}
"""

# ── 构建界面 ─────────────────────────────────────────────────────────
with gr.Blocks(css=CSS, title="EfficientEdit · 混合代码生成框架") as demo:
    # 顶部标题
    gr.HTML("""
    <div id="header-box">
        <h1>EfficientEdit · 混合代码生成框架</h1>
        <p>基于「检索 + 生成」的双模式代码编辑系统 &nbsp;|&nbsp; 课程设计 MVP</p>
        <div style="margin-top:16px;">
            <span class="mode-badge badge-m1">模式一</span>
            <span style="color:#7aadcc;font-size:0.82rem;">仅填写需求描述 → 系统自动检索代码库并生成</span>
        </div>
        <div style="margin-top:8px;">
            <span class="mode-badge badge-m2">模式二</span>
            <span style="color:#7aadcc;font-size:0.82rem;">同时提供原始代码 + 编辑指令 → 直接进行智能编辑</span>
        </div>
    </div>
    """)

    with gr.Row(equal_height=False):
        # ── 左侧：输入区 ──────────────────────────────────────────────
        with gr.Column(scale=5, elem_id="input-panel"):
            gr.HTML('<div class="section-label"> 输入</div>')

            source_code = gr.Textbox(
                label="原始代码（可选）— 留空则触发模式一检索",
                placeholder="# 粘贴待编辑的 Python 代码...\n# 留空时系统将自动从代码库检索最匹配的片段",
                lines=12,
                max_lines=20,
            )

            instruction = gr.Textbox(
                label="需求 / 指令（必填）",
                placeholder="示例：\n・添加一个参数控制排序方向（升序/降序）\n・计算列表的加权平均值\n・增加异常处理，连接失败时自动重试三次",
                lines=5,
            )

            with gr.Row():
                btn_run = gr.Button(" 生成代码", elem_id="btn-run", variant="primary")
                btn_clear = gr.Button("🗑 清空", elem_id="btn-clear")

            with gr.Accordion(" 开发选项", open=False):
                use_mock = gr.Checkbox(
                    label="使用 Mock 模式（后端未启动时勾选）",
                    value=False,
                )
                gr.HTML(
                    '<p style="color:#4a8fa8;font-size:0.78rem;margin:4px 0 0;">Mock 模式下不调用真实后端，仅用于前端调试。</p>'
                )

        # ── 右侧：输出区 ──────────────────────────────────────────────
        with gr.Column(scale=7, elem_id="output-panel"):
            gr.HTML('<div class="section-label"> 处理结果</div>')

            with gr.Tabs():
                with gr.TabItem(" 基础草稿"):
                    base_draft = gr.Textbox(
                        label="系统检索到 / 直接使用的基础草稿代码",
                        lines=10,
                        interactive=False,
                    )
                with gr.TabItem(" 生成补丁"):
                    patch_code = gr.Textbox(
                        label="LLM 生成的修改 / 新增代码块",
                        lines=10,
                        interactive=False,
                    )
                with gr.TabItem(" 最终代码"):
                    final_code = gr.Textbox(
                        label="融合后的完整代码（可直接复制使用）",
                        lines=10,
                        interactive=False,
                    )

            gr.HTML('<div class="divider"></div>')

            log_output = gr.Textbox(
                label=" 处理日志",
                lines=5,
                interactive=False,
                elem_id="log-box",
            )

            # 无人机可视化 iframe（检测到无人机相关代码时自动显示）
            drone_viz = gr.HTML(value="", label="")

    # ── 事件绑定 ─────────────────────────────────────────────────────
    btn_run.click(
        fn=process,
        inputs=[source_code, instruction, use_mock],
        outputs=[base_draft, patch_code, final_code, log_output, drone_viz],
    )

    btn_clear.click(
        fn=clear_all,
        inputs=[],
        outputs=[
            source_code,
            instruction,
            base_draft,
            patch_code,
            final_code,
            log_output,
            drone_viz,
        ],
    )

    # ── 无人机可视化入口 ───────────────────────────────────────────────
    with gr.Row():
        with gr.Column():
            gr.HTML("""
            <div style="margin-top:20px;background:linear-gradient(135deg,#0d1b2a,#0f2027);
                        border:1px solid #1e3a5f;border-radius:14px;padding:20px 24px;">
                <div style="display:flex;align-items:center;gap:12px;margin-bottom:12px;">
                    <span style="font-size:1.5rem;">🚁</span>
                    <span style="color:#4cc9f0;font-size:1rem;font-weight:700;letter-spacing:1px;">无人机路径 3D 可视化</span>
                </div>
                <p style="color:#7aadcc;font-size:0.82rem;margin:0 0 14px;">
                    生成完代码后，可在后端提供的 Three.js 场景中查看无人机飞行路径动画。
                    当检索到无人机相关代码（任务规划 / 控制器 / 路径规划）时，可视化将自动嵌入上方区域。
                    也可点击下方按钮在新标签页打开，或先检测模块是否在线。
                </p>
                <div style="display:flex;gap:10px;flex-wrap:wrap;">
                    <a href="http://127.0.0.1:8000/visualizer" target="_blank"
                       style="display:inline-block;padding:9px 20px;background:linear-gradient(135deg,#1d4ed8,#0891b2);
                              color:#fff;border-radius:8px;font-size:0.85rem;font-weight:600;text-decoration:none;">
                        🚀 打开 3D 可视化
                    </a>
                </div>
            </div>
            """)

    with gr.Row():
        with gr.Column():
            drone_status = gr.HTML(
                value="<span style='color:#4a8fa8;font-size:0.8rem;'>点击「检测」查看无人机可视化模块状态</span>",
                label="",
            )
            btn_drone_check = gr.Button("🔍 检测可视化模块状态", size="sm")

    btn_drone_check.click(fn=check_drone_status, inputs=[], outputs=[drone_status])


    gr.HTML("""
    <div style="text-align:center;margin-top:28px;color:#2d4a62;font-size:0.75rem;letter-spacing:1px;">
        EFFICIENTEDIT MVP &nbsp;·&nbsp; 成员E 前端原型 &nbsp;·&nbsp; 课程设计 2025
    </div>
    """)


if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        show_error=True,
    )
