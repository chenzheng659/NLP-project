/**
 * app.js — EfficientEdit 前端逻辑
 * 功能：调用 /generate API，渲染结果（diff / 前后代码 / 检索草稿 / 修改说明）
 */

// ── 监听源码输入，实时更新模式提示 ─────────────────
const sourceCodeEl = document.getElementById('source-code');
const modeHintText = document.getElementById('mode-hint-text');
const modeDot      = document.querySelector('.mode-dot');

sourceCodeEl.addEventListener('input', updateModeHint);

function updateModeHint() {
  const hasCode = sourceCodeEl.value.trim().length > 0;
  modeDot.className = 'mode-dot ' + (hasCode ? 'mode-edit' : 'mode-retrieval');
  if (hasCode) {
    modeHintText.innerHTML =
      '当前将使用 <strong>模式二（直接编辑）</strong>：以上方代码为草稿，按指令直接修改';
  } else {
    modeHintText.innerHTML =
      '当前将使用 <strong>模式一（检索生成）</strong>：系统自动从知识库检索最相关代码草稿';
  }
}

// ── Tab 切换 ────────────────────────────────────────
function switchTab(name) {
  const tabs     = document.querySelectorAll('.tab');
  const contents = document.querySelectorAll('.tab-content');

  tabs.forEach(t => t.classList.remove('active'));
  contents.forEach(c => c.classList.add('hidden'));

  document.getElementById('tab-' + name).classList.add('active');
  document.getElementById('tab-content-' + name).classList.remove('hidden');
}

// ── 复制代码 ────────────────────────────────────────
function copyCode(elementId) {
  const el  = document.getElementById(elementId);
  const btn = el.closest('.code-block-wrapper').querySelector('.copy-btn');
  navigator.clipboard.writeText(el.textContent).then(() => {
    const orig = btn.textContent;
    btn.textContent = '✓ 已复制';
    setTimeout(() => { btn.textContent = orig; }, 1800);
  }).catch(() => {
    btn.textContent = '✗ 复制失败';
    setTimeout(() => { btn.textContent = '复制'; }, 1800);
  });
}

// ── 提交处理 ────────────────────────────────────────
async function handleSubmit() {
  const instruction = document.getElementById('instruction').value.trim();
  const sourceCode  = sourceCodeEl.value.trim();
  const apiBase     = document.getElementById('api-url').value.trim().replace(/\/$/, '');

  // 验证
  if (!instruction) {
    showError('请填写自然语言指令后再提交。');
    return;
  }

  hideError();
  setLoading(true);

  const payload = { instruction };
  if (sourceCode) payload.source_code = sourceCode;

  try {
    const resp = await fetch(`${apiBase}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      let errMsg = `HTTP ${resp.status}`;
      try {
        const errBody = await resp.json();
        errMsg = errBody.detail || JSON.stringify(errBody);
      } catch (_) { /* ignore */ }
      throw new Error(errMsg);
    }

    const data = await resp.json();
    renderResult(data);

  } catch (err) {
    showError(`请求失败：${err.message}`);
  } finally {
    setLoading(false);
  }
}

// ── Mode / merge label config ────────────────────────────────────────────────
const MODE_CONFIG = {
  retrieval_generation: { label: '模式一：检索生成', chipClass: 'chip-mode-retrieval' },
  direct_edit:          { label: '模式二：直接编辑', chipClass: 'chip-mode-edit' },
};

const MERGE_CONFIG = {
  ast:  { label: '合并: AST',  chipClass: 'chip-merge-ast' },
  text: { label: '合并: TEXT', chipClass: 'chip-merge-text' },
};

// ── 渲染结果 ────────────────────────────────────────
function renderResult(data) {
  // Meta chips
  const modeConf    = MODE_CONFIG[data.mode]  || { label: data.mode,         chipClass: 'chip-mode-edit' };
  const mergeConf   = MERGE_CONFIG[data.merge_method] || { label: data.merge_method, chipClass: 'chip-merge-text' };
  const changedLabel = data.changed ? '有修改' : '无修改';
  const changedClass = data.changed ? 'chip-changed-yes' : 'chip-changed-no';

  document.getElementById('result-meta').innerHTML = `
    <span class="meta-chip ${modeConf.chipClass}">${modeConf.label}</span>
    <span class="meta-chip ${changedClass}">${changedLabel}</span>
    <span class="meta-chip ${mergeConf.chipClass}">${mergeConf.label}</span>
  `;

  // Diff
  setHighlighted('diff-code',     data.diff || '（无 diff）', 'diff');
  // Before / After
  setHighlighted('before-code',   data.before_code || '', 'python');
  setHighlighted('after-code',    data.after_code  || '', 'python');

  // 检索草稿 tab（仅模式一且有草稿时显示）
  const retrievedTab = document.getElementById('tab-retrieved');
  if (data.retrieved_code) {
    retrievedTab.style.display = '';
    setHighlighted('retrieved-code', data.retrieved_code, 'python');
  } else {
    retrievedTab.style.display = 'none';
  }

  // Patch note
  const patchBox = document.getElementById('patch-note-box');
  if (data.patch_note) {
    patchBox.innerHTML = `<strong>修改说明：</strong>${escapeHtml(data.patch_note)}`;
    patchBox.style.display = 'block';
  } else {
    patchBox.style.display = 'none';
  }

  // Show result panel and switch to diff tab
  const resultPanel = document.getElementById('result-panel');
  resultPanel.style.display = 'block';
  switchTab('diff');

  // Smooth scroll to results
  resultPanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// ── 工具函数 ────────────────────────────────────────

/** 将代码写入 <code> 元素并触发 highlight.js */
function setHighlighted(elementId, code, lang) {
  const el = document.getElementById(elementId);
  el.textContent = code;
  el.className   = `language-${lang}`;
  hljs.highlightElement(el);
}

/** HTML 转义（用于普通文本插入） */
function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

/** 显示错误提示 */
function showError(msg) {
  const box = document.getElementById('error-box');
  document.getElementById('error-msg').textContent = msg;
  box.classList.remove('hidden');
}

/** 隐藏错误提示 */
function hideError() {
  document.getElementById('error-box').classList.add('hidden');
}

/** 按钮加载状态切换 */
function setLoading(isLoading) {
  const btn     = document.getElementById('submit-btn');
  const label   = document.getElementById('btn-label');
  const spinner = document.getElementById('btn-spinner');

  btn.disabled = isLoading;
  if (isLoading) {
    label.textContent = '生成中…';
    spinner.classList.remove('hidden');
  } else {
    label.textContent = '🚀 生成代码';
    spinner.classList.add('hidden');
  }
}

// ── 支持 Ctrl/Cmd+Enter 快捷提交 ───────────────────
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    handleSubmit();
  }
});
