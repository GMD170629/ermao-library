const app = document.querySelector('#app');
const icons = await fetch('/prototypes/feedback-web/icons.json').then((response) => response.json());

const icon = (name) => (icons[name] || '').replace('<svg ', '<svg class="icon" ');
const escapeHtml = (value = '') => String(value).replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[character]);
const templates = {
  suggestion: '### 我希望增加或改善\n\n\n### 使用场景\n\n\n### 期望效果\n\n',
  issue: '### 遇到的现象\n\n\n### 我做了什么\n\n\n### 期望结果\n\n'
};
const uploadLimit = { count: 5, bytes: 10 * 1024 * 1024, totalBytes: 15 * 1024 * 1024 };
const imageTypes = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);
const allowedExtensions = /\.(png|jpe?g|webp|gif|pdf|txt|log|zip)$/i;

function emptyForm(kind = 'suggestion', logId = null) {
  return { kind, description: templates[kind], qq: '', groupName: '', email: '', includeLog: Boolean(logId), includeEnvironment: false, logId };
}

function formatBytes(bytes) {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

function environmentItems() {
  const userAgent = navigator.userAgent;
  const browser = /Edg\//.test(userAgent) ? 'Edge' : /Firefox\//.test(userAgent) ? 'Firefox' : /Chrome\//.test(userAgent) ? 'Chrome' : /Safari\//.test(userAgent) ? 'Safari' : '其他浏览器';
  return [
    ['应用版本', 'v1.5.1（演示）'],
    ['安装方式', 'Docker Compose（演示；正式版由服务器提供）'],
    ['客户端', window.matchMedia('(display-mode: standalone)').matches ? 'PWA' : 'Web 浏览器'],
    ['浏览器与系统', `${browser} · ${navigator.userAgentData?.platform || navigator.platform || '未知平台'}`],
    ['语言', document.documentElement.lang || 'zh-CN'],
    ['时区', Intl.DateTimeFormat().resolvedOptions().timeZone || '未知'],
    ['窗口尺寸', `${window.innerWidth} × ${window.innerHeight}`],
    ['当前页面', state.page === 'logs' ? '/settings/logs' : '/settings/about']
  ];
}

function environmentPreview() {
  return `<div class="preview-box"><strong>将同步的系统环境</strong><dl class="environment-list">${environmentItems().map(([label, value]) => `<dt>${label}</dt><dd>${escapeHtml(value)}</dd>`).join('')}</dl><p class="form-hint">不包含账号、令牌、IP 地址、书库路径或图书列表。</p></div>`;
}

const events = [
  {
    id: 'LOG-240929-0732', time: '2026/09/29 07:32', level: 'error', source: '导入',
    summary: '批量导入时，3 本图书中的 1 本未能建立阅读资源',
    stage: 'import.prepare_resource', exception: 'ResourcePreparationError',
    details: 'PDF 资源索引未生成，任务在写入图书记录前停止。',
    books: ['《海边的信》· 导入失败', '《灯塔之下》· 同批次成功', '《远山集》· 同批次成功'],
    related: ['LOG-240929-0731 · 批量导入开始', 'LOG-240929-0733 · 同批次其他图书完成'],
    traceback: 'ResourcePreparationError: failed to prepare reading resource\n  at import.prepare_resource\n  caused by: PDF index unavailable'
  },
  {
    id: 'LOG-240929-0648', time: '2026/09/29 06:48', level: 'warning', source: '下载',
    summary: '远程资源暂时不可用，已按既有策略等待重试', stage: 'download.fetch',
    exception: 'TemporaryUnavailable', details: '当前为警告记录，尚未产生最终失败。',
    books: ['《北方列车》'], related: [], traceback: ''
  },
  {
    id: 'LOG-240928-2215', time: '2026/09/28 22:15', level: 'error', source: '书库',
    summary: '书库扫描时无法读取一项图书资源', stage: 'library.scan_source',
    exception: 'SourceReadError', details: '该资源的元数据读取失败，其他图书扫描继续。',
    books: ['《雨后的图书馆》· 读取失败', '《白昼来信》· 同目录、未受影响'],
    related: ['LOG-240928-2214 · 同目录扫描开始'],
    traceback: 'SourceReadError: could not inspect source metadata\n  at library.scan_source'
  }
];

const state = {
  page: 'about', role: 'manager', notice: '', level: 'all', source: 'all', search: '',
  appliedSearch: '', expandedLog: '', emailOpen: false, previewOpen: false, environmentOpen: false,
  failNext: false, modal: null,
  form: emptyForm(), editorTab: 'write', uploads: [], uploadError: '', deletedCount: 0,
  errors: {}
};

function button(label, action, variant = 'secondary', iconName = '', extra = '') {
  return `<button type="button" class="btn btn-${variant}" data-action="${action}" ${extra}>${iconName ? icon(iconName) : ''}${label}</button>`;
}

function navButton(label, iconName, page, active = false, extra = '') {
  return `<button type="button" class="nav-button ${active ? 'active' : ''}" data-action="page" data-page="${page}" ${extra}>${icon(iconName)}<span>${label}</span></button>`;
}

function shell(content) {
  const isAbout = state.page === 'about';
  return `<div class="layout">
    <aside class="sidebar">
      <div class="brand"><img src="/apps/web/public/icons/icon-192.png" alt="" />二毛图书</div>
      <div class="back-link">${icon('ArrowLeft')}<span>返回阅读</span></div>
      <div class="side-scroll">
        <div class="side-group"><div class="side-heading">用户设置</div>
          ${navButton('个人信息', 'UserRound', 'about')}
          ${navButton('邮件与 Kindle', 'Mail', 'about')}
          ${navButton('自动化授权', 'BookKey', 'about')}
        </div>
        ${state.role === 'manager' ? `<div class="side-group"><div class="side-heading">系统设置</div>
          ${navButton('用户管理', 'Users', 'logs')}
          ${navButton('书库来源和导入', 'Database', 'logs')}
          ${navButton('智能整理', 'Sparkles', 'logs')}
          ${navButton('OPDS', 'BookKey', 'logs')}
          ${navButton('数据和系统', 'Database', 'logs')}
          ${navButton('系统健康检查', 'Activity', 'logs')}
          ${navButton('系统日志', 'FileText', 'logs', !isAbout)}
        </div>` : ''}
        <div class="side-group">${navButton('关于', 'Info', 'about', isAbout)}</div>
      </div>
      <div class="account"><img src="/apps/web/public/icons/icon-192.png" alt="" /><div><div class="account-name">演示用户</div><div class="account-sub">账户与设置</div></div>${icon('ChevronRight')}</div>
      <div class="mobile-nav">
        <button type="button" data-action="page" data-page="about" class="${isAbout ? 'active' : ''}">关于</button>
        ${state.role === 'manager' ? `<button type="button" data-action="page" data-page="logs" class="${!isAbout ? 'active' : ''}">系统日志</button>` : ''}
      </div>
    </aside>
    <div class="main"><main class="content"><h1 class="eyebrow">设置</h1>${state.notice ? `<div class="notice">${escapeHtml(state.notice)}</div>` : ''}${content}</main></div>
  </div>
  <div class="demo-bar"><strong>交互原型 · 演示数据</strong><label>视角 <select data-demo-role><option value="manager" ${state.role === 'manager' ? 'selected' : ''}>管理员</option><option value="reader" ${state.role === 'reader' ? 'selected' : ''}>普通用户</option></select></label><label><input type="checkbox" data-demo-fail ${state.failNext ? 'checked' : ''} /> 下次提交失败</label></div>
  ${state.modal ? feedbackModal() : ''}`;
}

function aboutPage() {
  return `<div class="page-head"><div><h2>关于</h2><p>查看 二毛图书 的版本、项目地址与开源信息。</p></div></div>
    <div class="card about-summary">
      <div class="summary-top"><div class="summary-brand"><img src="/apps/web/public/icons/icon-192.png" alt="二毛图书应用图标" /><div><h3>二毛图书</h3><p>自托管私人图书馆与沉浸阅读应用</p></div></div><div class="version"><span class="version-label">当前版本</span><div class="version-num">v1.5.1</div></div></div>
      <div class="summary-facts"><div class="fact">${icon('Layers3')}<div><div class="fact-label">运行方式</div><div class="fact-value">自托管 Web 应用 / PWA</div></div></div><div class="fact">${icon('BookOpen')}<div><div class="fact-label">支持格式</div><div class="fact-value">EPUB、CBZ/CBR、PDF、TXT 与音频</div></div></div><div class="fact">${icon('Scale')}<div><div class="fact-label">开源许可</div><div class="fact-value">MIT License</div></div></div></div>
    </div>
    <div class="card feedback-card"><div class="feedback-card-info"><div class="icon-well">${icon('MessageSquarePlus')}</div><div><h3>帮助改进二毛图书</h3><p>提出功能建议，或告诉我们你遇到的问题。提交前可以核对将发送的信息。</p></div></div><div class="feedback-card-actions">${button('功能建议', 'open-suggestion', 'secondary')}${button('报告问题', 'open-issue', 'primary', 'Send')}</div></div>
    <section class="section-divider"><h3>更新与版本历史</h3><p>更新说明与 GitHub Release 保持一致。</p><div class="release-sample">${icon('CheckCircle2')}更新成功，实际运行版本 v1.5.1。</div></section>
    <section class="section-divider"><h3>项目介绍</h3><p>二毛图书 是一款面向个人藏书的开源、自托管阅读与书库管理应用。它提供读物导入、整理、检索、阅读与收听能力，适合部署在家庭 NAS 上，并通过浏览器在不同设备间访问。</p></section>
    <section class="section-divider"><h3>项目地址</h3><div class="project-link">${icon('ExternalLink')}github.com/GMD170629/ermao-library</div></section>`;
}

function filteredEvents() {
  return events.filter((event) =>
    (state.level === 'all' || state.level === event.level)
    && (state.source === 'all' || state.source === event.source)
    && (!state.appliedSearch || `${event.summary} ${event.id} ${event.books.join(' ')}`.toLowerCase().includes(state.appliedSearch.toLowerCase()))
  );
}

function chip(label, key, value, selected) {
  return `<button type="button" class="chip ${selected ? 'active' : ''}" data-action="filter" data-filter="${key}" data-value="${value}">${label}</button>`;
}

function eventDetail(event) {
  return `<div class="log-detail"><div class="detail-grid"><div><span class="muted">事件编号：</span>${event.id}</div><div><span class="muted">执行阶段：</span>${event.stage}</div><div><span class="muted">异常类型：</span>${event.exception}</div><div><span class="muted">关联图书：</span>${event.books.length} 本</div></div>
    <p style="margin-top:10px">${event.details}</p>
    <div class="preview-box"><strong>关联图书</strong><ul>${event.books.map((book) => `<li>${escapeHtml(book)}</li>`).join('')}</ul></div>
    ${event.traceback ? `<pre class="log-code">${escapeHtml(event.traceback)}</pre>` : ''}
    <div class="detail-actions"><span class="muted tiny">此处为演示日志；实际流程按事件关联范围读取。</span>${event.level === 'error' ? button('反馈此问题', 'open-from-log', 'primary', 'Send', `data-event="${event.id}"`) : ''}</div>
  </div>`;
}

function logsPage() {
  const shown = filteredEvents();
  return `<div class="page-head"><div><h2>系统日志</h2><p>查看导入、整理、下载与系统操作产生的真实记录。</p></div>${button('手动报告问题', 'open-issue', 'secondary', 'MessageSquarePlus')}</div>
    <section class="card log-storage"><div class="storage-row"><div class="storage-title">${icon('HardDrive')}<div><h3>日志容量管理</h3><p>当前使用 0.7 MB / 5 MB<br /><span class="tiny">尚未执行自动清理</span></p></div></div><div class="storage-controls"><label>容量上限（MB）<input class="input" value="5" aria-label="容量上限" /></label>${button('保存', 'demo-only')}</div></div><div class="progress"><span></span></div></section>
    <section class="card filters" aria-label="日志筛选"><div class="chip-row">
      ${chip('全部级别', 'level', 'all', state.level === 'all')}${chip('信息', 'level', 'info', state.level === 'info')}${chip('警告', 'level', 'warning', state.level === 'warning')}${chip('错误', 'level', 'error', state.level === 'error')}
      <span class="chip-separator"></span>${chip('全部来源', 'source', 'all', state.source === 'all')}${['导入', '下载', '书库'].map((source) => chip(source, 'source', source, state.source === source)).join('')}
    </div><div class="filter-fields"><label class="field-label">开始日期<input class="input" type="date" /></label><label class="field-label">结束日期<input class="input" type="date" /></label><label class="field-label">关键字<input class="input" data-search value="${escapeHtml(state.search)}" placeholder="搜索摘要、动作或关联对象" /></label></div>
    <div class="filter-actions">${button('搜索', 'search', 'secondary', 'Search')}${button('刷新', 'reset-filters', 'secondary', 'RefreshCw')}${button('导出', 'demo-only', 'secondary', 'Download')}${button('清理', 'demo-only', 'ghost')}</div></section>
    <div class="card log-table"><div class="log-table-head"><div>时间</div><div>级别</div><div>来源</div><div>摘要</div><div style="text-align:right">详情</div></div>
      ${shown.length ? shown.map((event) => `<div class="log-row"><div class="time">${event.time}</div><div><span class="badge badge-${event.level === 'error' ? 'red' : event.level === 'warning' ? 'amber' : 'slate'}">${event.level === 'error' ? '错误' : event.level === 'warning' ? '警告' : '信息'}</span></div><div>${event.source}</div><div class="summary" title="${escapeHtml(event.summary)}">${escapeHtml(event.summary)}</div><button type="button" class="text-link" data-action="expand-log" data-event="${event.id}" aria-expanded="${state.expandedLog === event.id}">${state.expandedLog === event.id ? '收起详情' : '查看详情'}</button></div>${state.expandedLog === event.id ? eventDetail(event) : ''}`).join('') : '<div class="empty">当前筛选条件下暂无日志。</div>'}
    </div><p class="log-count">共 ${shown.length} 条记录 · 均为原型演示数据</p>`;
}

function field(name, label, placeholder = '', required = false, type = 'text') {
  const value = escapeHtml(state.form[name]);
  return `<div class="form-row"><label for="field-${name}">${label}${required ? ' <span class="required">*</span>' : ''}</label><input id="field-${name}" class="input" type="${type}" name="${name}" value="${value}" placeholder="${placeholder}" ${required ? 'required' : ''} />${state.errors[name] ? `<div class="form-error">${state.errors[name]}</div>` : ''}</div>`;
}

function markdownPreview(markdown) {
  const inline = (line) => escapeHtml(line)
    .replace(/!\[([^\]]*)\]\(upload:([a-z0-9-]+)\)/gi, (_, alt, id) => {
      const image = state.uploads.find((item) => item.id === id && item.isImage);
      return image ? `<img class="inline-image" src="${image.url}" alt="${alt}" />` : '<em>图片已移除</em>';
    })
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
  return markdown.split(/\r?\n/).map((line) => {
    if (/^###\s+/.test(line)) return `<h4>${inline(line.replace(/^###\s+/, ''))}</h4>`;
    if (/^[-*]\s+/.test(line)) return `<div class="markdown-list">• ${inline(line.replace(/^[-*]\s+/, ''))}</div>`;
    return line.trim() ? `<p>${inline(line)}</p>` : '<div class="markdown-gap"></div>';
  }).join('');
}

function uploadList() {
  if (!state.uploads.length) return '';
  return `<div class="upload-list">${state.uploads.map((item) => `<div class="upload-item">${item.isImage ? `<img src="${item.url}" alt="" />` : `<div class="upload-file-icon">${icon('Paperclip')}</div>`}<div class="upload-info"><strong>${escapeHtml(item.name)}</strong><span>${formatBytes(item.size)} · ${item.isImage ? '图片' : '附件'} · 待随反馈提交</span></div><button type="button" class="icon-close" data-action="remove-upload" data-upload-id="${item.id}" aria-label="移除 ${escapeHtml(item.name)}">${icon('X')}</button></div>`).join('')}</div>`;
}

function editor() {
  const label = state.form.kind === 'issue' ? '问题描述' : '详细说明';
  return `<div class="form-row"><label for="field-description">${label} <span class="required">*</span></label>
    <div class="editor-shell" data-editor-dropzone><div class="editor-toolbar"><div class="editor-tools"><button type="button" data-action="bold" aria-label="加粗" title="加粗">${icon('Bold')}</button><button type="button" data-action="list" aria-label="插入列表" title="插入列表">${icon('List')}</button><span class="toolbar-divider"></span><button type="button" data-action="pick-image" aria-label="上传图片" title="上传图片">${icon('ImagePlus')}</button><button type="button" data-action="pick-file" aria-label="上传附件" title="上传附件">${icon('Paperclip')}</button></div><div class="editor-switch"><button type="button" class="${state.editorTab === 'write' ? 'active' : ''}" data-action="editor-write">编辑</button><button type="button" class="${state.editorTab === 'preview' ? 'active' : ''}" data-action="editor-preview">预览</button></div></div>
      ${state.editorTab === 'write' ? `<textarea id="field-description" class="markdown-input" name="description" spellcheck="false" aria-label="${label}">${escapeHtml(state.form.description)}</textarea>` : `<div class="markdown-output" role="region" aria-label="Markdown 预览">${markdownPreview(state.form.description)}</div>`}
      <div class="editor-bottom">支持 Markdown · 可拖入图片或文件 · 最多 ${uploadLimit.count} 个、单个不超过 10 MB、合计不超过 15 MB</div>
    </div><input class="sr-only" type="file" data-upload-input="image" accept="image/png,image/jpeg,image/webp,image/gif" multiple tabindex="-1" /><input class="sr-only" type="file" data-upload-input="file" accept=".png,.jpg,.jpeg,.webp,.gif,.pdf,.txt,.log,.zip" multiple tabindex="-1" />
    ${state.errors.description ? `<div class="form-error">${state.errors.description}</div>` : ''}${state.uploadError ? `<div class="form-error">${escapeHtml(state.uploadError)}</div>` : ''}${uploadList()}
    <p class="form-hint">已放入可编辑的填写提纲；不需要的标题可以删掉。图片会插入正文，其他附件列在正文下方。</p></div>`;
}

function attachmentPreview(event) {
  return `<div class="preview-box"><strong>将附带的日志信息</strong><ul><li>${event.id} · ${escapeHtml(event.summary)}</li><li>执行阶段：${event.stage}；异常：${event.exception}</li>${event.related.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}${event.books.map((book) => `<li>关联图书：${escapeHtml(book)}</li>`).join('')}</ul>${event.traceback ? `<pre class="log-code">${escapeHtml(event.traceback)}</pre>` : ''}</div>`;
}

function modalForm() {
  const isIssue = state.form.kind === 'issue';
  const event = events.find((item) => item.id === state.form.logId);
  return `<div class="tabs" role="tablist" aria-label="反馈类型"><button type="button" class="tab ${!isIssue ? 'active' : ''}" data-action="kind" data-kind="suggestion" role="tab" aria-selected="${!isIssue}">功能建议</button><button type="button" class="tab ${isIssue ? 'active' : ''}" data-action="kind" data-kind="issue" role="tab" aria-selected="${isIssue}">遇到问题</button></div>
    ${event && isIssue ? `<div class="log-attachment"><div class="log-attachment-head"><div><h3>已关联日志 ${event.id}</h3><p>${escapeHtml(event.summary)}</p></div><span class="badge badge-red">错误</span></div><label class="checkline"><input type="checkbox" name="includeLog" ${state.form.includeLog ? 'checked' : ''} />提交时附上这条日志、直接关联的事件和图书</label><button type="button" class="disclosure" data-action="preview-log">${state.previewOpen ? '收起将发送的日志' : '查看将发送的日志'}</button>${state.previewOpen ? attachmentPreview(event) : ''}</div>` : ''}
    ${editor()}
    <section class="subsection"><h3>系统环境（选填）</h3><p>需要协助定位问题时，可以同步应用与设备的基本信息。</p><label class="checkline"><input type="checkbox" name="includeEnvironment" ${state.form.includeEnvironment ? 'checked' : ''} />同步安装方式、版本号、客户端与当前页面</label><button type="button" class="disclosure" data-action="preview-environment">${state.environmentOpen ? '收起环境信息' : '查看会收集哪些信息'}</button>${state.environmentOpen ? environmentPreview() : ''}</section>
    <section class="subsection"><h3>联系方式（选填）</h3><p>不填写也可以提交。留一种即可，方便我们进一步了解情况。</p><div class="contact-grid">${field('qq', 'QQ 号', '方便联系你的 QQ 号')}${field('groupName', '官方交流群昵称', '仅群成员填写')}</div><button type="button" class="disclosure" data-action="toggle-email">${state.emailOpen ? '收起邮箱联系方式' : '使用邮箱联系'}</button>${state.emailOpen ? field('email', '邮箱', 'name@example.com', false, 'email') : ''}</section>
    <div class="privacy-note">${icon('ShieldCheck')}<span>仅在你确认提交后发送正文、所选文件及你勾选的诊断信息。官网发送邮件后立即清除临时文件；发送失败也清除服务器临时文件，浏览器保留本次草稿供重试。邮件中的附件仍会留在收件邮箱。</span></div>`;
}

function reviewRow(label, value) { return `<dt>${label}</dt><dd>${value || '未填写'}</dd>`; }

function modalReview() {
  const event = events.find((item) => item.id === state.form.logId);
  const contact = [state.form.qq && `QQ：${escapeHtml(state.form.qq)}`, state.form.groupName && `官方群昵称：${escapeHtml(state.form.groupName)}`, state.form.email && `邮箱：${escapeHtml(state.form.email)}`].filter(Boolean).join(' · ');
  return `<div class="notice">请核对以下内容。点击「确认提交」后，正式功能会把这些信息发往官网；此原型不会联网提交。</div>
    <div class="review-block"><h3>${state.form.kind === 'issue' ? '问题描述' : '详细说明'}</h3><div class="markdown-output review-markdown">${markdownPreview(state.form.description)}</div><dl>${reviewRow('类型', state.form.kind === 'issue' ? '遇到问题' : '功能建议')}${reviewRow('联系方式', contact)}</dl></div>
    <div class="review-block"><h3>图片与附件 · ${state.uploads.length} 个</h3>${state.uploads.length ? `<div class="review-files">${state.uploads.map((item) => `<div>${item.isImage ? icon('FileImage') : icon('Paperclip')}<span>${escapeHtml(item.name)}</span><small>${formatBytes(item.size)}</small></div>`).join('')}</div>` : '<p>未选择文件。</p>'}<p class="form-hint">官网在本次邮件发送结束后立即清除临时文件，成功或失败都清除。</p></div>
    <div class="review-block"><h3>诊断信息</h3>${event && state.form.includeLog ? attachmentPreview(event) : '<p>未附带系统日志。</p>'}${state.form.includeEnvironment ? environmentPreview() : '<p style="margin-top:8px">未同步系统环境。</p>'}</div>
    <div class="privacy-note">${icon('ShieldCheck')}<span>官网保留反馈文字与编号，文件只用于本次邮件。服务器临时文件在发送结束后清除；失败时浏览器仍保留草稿和本地文件供重试。收件邮箱中的附件由邮箱保存。</span></div>`;
}

function modalOutcome() {
  if (state.modal.step === 'sending') return `<div class="outcome"><div class="spinner"></div><h3>正在提交</h3><p>请稍候，演示即将进入成功或失败状态。</p></div>`;
  if (state.modal.step === 'success') return `<div class="outcome"><div class="outcome-icon">${icon('CheckCircle2')}</div><h3>反馈已收到</h3><p>这是原型演示成功状态。正式功能会由官网发送邮件，并清除临时文件。</p><div class="receipt">FB-20260929-1042</div>${state.deletedCount ? `<p class="success-cleanup">${icon('Trash2')}本次 ${state.deletedCount} 个演示文件的临时预览已清除</p>` : ''}<p class="tiny">请保存反馈编号，方便之后在交流群中沟通。</p></div>`;
  return `<div class="outcome"><div class="outcome-icon error">${icon('AlertCircle')}</div><h3>提交暂时失败</h3><p>官网临时文件已清除；正文和所选文件仍保留在当前浏览器。你可以重试，或返回修改后再提交。</p></div>`;
}

function feedbackModal() {
  const step = state.modal.step;
  const title = step === 'review' ? '核对反馈内容' : step === 'form' ? '反馈与报错' : '反馈与报错';
  const subtitle = step === 'form' ? '分享想法，或把遇到的问题告诉我们。' : step === 'review' ? '这些内容将发往二毛图书官网服务器。' : '原型中的提交仅演示界面状态。';
  return `<div class="overlay" data-action="overlay"><section class="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><div class="dialog-head"><div class="dialog-title"><div class="icon-well">${icon('MessageSquarePlus')}</div><div><h2 id="dialog-title">${title}</h2><p>${subtitle}</p></div></div><button type="button" class="icon-close" data-action="close" aria-label="关闭弹窗">${icon('X')}</button></div>
    <div class="dialog-body">${step === 'form' ? modalForm() : step === 'review' ? modalReview() : modalOutcome()}</div>
    <div class="dialog-footer"><div class="dialog-footer-note">交互原型 · 不会发送真实反馈</div><div class="dialog-footer-actions">${step === 'form' ? `${button('取消', 'close', 'secondary')}${button('核对内容', 'review', 'primary', 'ChevronRight')}` : step === 'review' ? `${button('返回修改', 'back-form', 'secondary')}${button('确认提交', 'submit', 'primary', 'Send')}` : step === 'failure' ? `${button('返回修改', 'back-form', 'secondary')}${button('重试提交', 'submit', 'primary', 'RefreshCw')}` : step === 'success' ? button('完成', 'close', 'primary', 'Check') : ''}</div></div>
  </section></div>`;
}

function render() {
  app.innerHTML = shell(state.page === 'about' ? aboutPage() : logsPage());
  document.body.style.overflow = state.modal ? 'hidden' : '';
}

function clearUploads() {
  for (const item of state.uploads) URL.revokeObjectURL(item.url);
  state.uploads = [];
  state.uploadError = '';
}

function closeFeedback() {
  clearUploads();
  state.form = emptyForm();
  state.deletedCount = 0;
  state.errors = {};
  state.modal = null;
}

function addUploads(files) {
  state.uploadError = '';
  for (const file of files) {
    if (state.uploads.length >= uploadLimit.count) { state.uploadError = `最多添加 ${uploadLimit.count} 个文件。`; break; }
    if (!allowedExtensions.test(file.name) || (file.type.startsWith('image/') && !imageTypes.has(file.type))) {
      state.uploadError = `不支持 ${file.name}；请使用图片、PDF、TXT、LOG 或 ZIP。`;
      continue;
    }
    if (file.size > uploadLimit.bytes) { state.uploadError = `${file.name} 超过单文件 10 MB 限制。`; continue; }
    if (state.uploads.reduce((total, item) => total + item.size, 0) + file.size > uploadLimit.totalBytes) {
      state.uploadError = `文件总大小不能超过 15 MB；${file.name} 未添加。`;
      continue;
    }
    const item = { id: `u${Date.now()}-${Math.random().toString(36).slice(2, 7)}`, name: file.name, size: file.size, isImage: imageTypes.has(file.type), file, url: URL.createObjectURL(file) };
    state.uploads.push(item);
    if (item.isImage) state.form.description += `\n![${file.name.replace(/[\[\]()]/g, '')}](upload:${item.id})\n`;
  }
  render();
}

function insertMarkdown(before, after, fallback) {
  const textarea = app.querySelector('#field-description');
  if (!(textarea instanceof HTMLTextAreaElement)) return;
  const start = textarea.selectionStart;
  const end = textarea.selectionEnd;
  const selected = textarea.value.slice(start, end) || fallback;
  const value = `${textarea.value.slice(0, start)}${before}${selected}${after}${textarea.value.slice(end)}`;
  state.form.description = value;
  textarea.value = value;
  textarea.focus();
  textarea.setSelectionRange(start + before.length, start + before.length + selected.length);
}

function openFeedback(kind, logId = null) {
  const sameDraft = state.form.kind === kind && state.form.logId === logId;
  if (!sameDraft) { clearUploads(); state.form = emptyForm(kind, logId); }
  state.form.kind = kind;
  state.form.logId = logId;
  state.form.includeLog = Boolean(logId);
  state.previewOpen = false;
  state.environmentOpen = false;
  state.editorTab = 'write';
  state.errors = {};
  state.modal = { step: 'form' };
  render();
}

function validate() {
  const errors = {};
  const userText = state.form.description.replace(/^###\s+.*$/gm, '').replace(/!\[[^\]]*\]\(upload:[^)]+\)/g, '').replace(/[\s*`#-]/g, '').trim();
  if (!userText) errors.description = '请在提纲中填写具体内容';
  if (state.form.qq.trim() && !/^\d{1,20}$/.test(state.form.qq.trim())) errors.qq = 'QQ 号请填写数字';
  if (state.form.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(state.form.email.trim())) errors.email = '请填写有效邮箱地址';
  state.errors = errors;
  return Object.keys(errors).length === 0;
}

function simulateSubmit() {
  state.modal.step = 'sending';
  const activeModal = state.modal;
  render();
  window.setTimeout(() => {
    if (state.modal !== activeModal) return;
    state.modal.step = state.failNext ? 'failure' : 'success';
    if (state.modal.step === 'success') { state.deletedCount = state.uploads.length; clearUploads(); }
    state.failNext = false;
    render();
  }, 680);
}

app.addEventListener('click', (event) => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  const action = target.dataset.action;
  if (action === 'overlay' && event.target !== target) return;
  if (action === 'page') {
    state.page = target.dataset.page;
    state.notice = '';
    window.scrollTo(0, 0);
  } else if (action === 'open-suggestion') openFeedback('suggestion');
  else if (action === 'open-issue') openFeedback('issue');
  else if (action === 'open-from-log') openFeedback('issue', target.dataset.event);
  else if (action === 'close' || action === 'overlay') {
    closeFeedback();
  } else if (action === 'kind') {
    const oldKind = state.form.kind;
    const leavingLog = state.form.logId && target.dataset.kind === 'suggestion';
    state.form.kind = target.dataset.kind;
    if (state.form.description.trim() === templates[oldKind].trim()) state.form.description = templates[state.form.kind];
    if (leavingLog) state.form.logId = null;
  } else if (action === 'toggle-email') state.emailOpen = !state.emailOpen;
  else if (action === 'preview-log') state.previewOpen = !state.previewOpen;
  else if (action === 'preview-environment') state.environmentOpen = !state.environmentOpen;
  else if (action === 'editor-write') state.editorTab = 'write';
  else if (action === 'editor-preview') state.editorTab = 'preview';
  else if (action === 'bold') insertMarkdown('**', '**', '重点内容');
  else if (action === 'list') insertMarkdown('- ', '', '列表项');
  else if (action === 'pick-image') app.querySelector('[data-upload-input="image"]')?.click();
  else if (action === 'pick-file') app.querySelector('[data-upload-input="file"]')?.click();
  else if (action === 'remove-upload') {
    const item = state.uploads.find((upload) => upload.id === target.dataset.uploadId);
    if (item) {
      URL.revokeObjectURL(item.url);
      state.uploads = state.uploads.filter((upload) => upload.id !== item.id);
      state.form.description = state.form.description.replace(new RegExp(`!?\\[[^\\]]*\\]\\(upload:${item.id}\\)`, 'g'), '');
    }
  }
  else if (action === 'review') { if (validate()) state.modal.step = 'review'; }
  else if (action === 'back-form') state.modal.step = 'form';
  else if (action === 'submit') simulateSubmit();
  else if (action === 'filter') { state[target.dataset.filter] = target.dataset.value; state.expandedLog = ''; }
  else if (action === 'search') { state.appliedSearch = state.search.trim(); state.expandedLog = ''; }
  else if (action === 'reset-filters') { state.level = 'all'; state.source = 'all'; state.search = ''; state.appliedSearch = ''; state.expandedLog = ''; }
  else if (action === 'expand-log') state.expandedLog = state.expandedLog === target.dataset.event ? '' : target.dataset.event;
  else if (action === 'demo-only') state.notice = '此处保持当前系统页面样式；反馈原型没有连接日志管理操作。';
  if (!['open-suggestion', 'open-issue', 'open-from-log', 'submit', 'bold', 'list', 'pick-image', 'pick-file'].includes(action)) render();
});

app.addEventListener('input', (event) => {
  if (event.target.matches('[name]') && event.target.name in state.form && event.target.type !== 'checkbox') state.form[event.target.name] = event.target.value;
  if (event.target.matches('[data-search]')) state.search = event.target.value;
});

app.addEventListener('change', (event) => {
  if (event.target.matches('[data-upload-input]')) { addUploads(Array.from(event.target.files || [])); return; }
  if (event.target.name === 'includeLog') state.form.includeLog = event.target.checked;
  if (event.target.name === 'includeEnvironment') { state.form.includeEnvironment = event.target.checked; state.environmentOpen = event.target.checked; render(); }
  if (event.target.matches('[data-demo-role]')) {
    state.role = event.target.value;
    state.notice = state.role === 'reader' ? '普通用户可从「关于」手动描述问题；系统日志入口仅对有管理权限的用户开放。' : '';
    if (state.role === 'reader') state.page = 'about';
    render();
  }
  if (event.target.matches('[data-demo-fail]')) state.failNext = event.target.checked;
});

app.addEventListener('dragover', (event) => {
  if (!event.target.closest('[data-editor-dropzone]')) return;
  event.preventDefault();
});

app.addEventListener('drop', (event) => {
  if (!event.target.closest('[data-editor-dropzone]')) return;
  event.preventDefault();
  addUploads(Array.from(event.dataTransfer?.files || []));
});

app.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && state.modal) { closeFeedback(); render(); }
  if (event.key === 'Enter' && event.target.matches('[data-search]')) { state.appliedSearch = state.search.trim(); state.expandedLog = ''; render(); }
});

render();
