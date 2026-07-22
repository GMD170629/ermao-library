import { useMemo, useState } from "react";
import {
  ArrowLeft,
  ArrowsMerge,
  BookOpenText,
  Books,
  CaretDown,
  CaretRight,
  Check,
  CheckCircle,
  CheckSquare,
  ClockCounterClockwise,
  DotsThree,
  Funnel,
  Gear,
  GridFour,
  House,
  List,
  MagnifyingGlass,
  PencilSimple,
  Plus,
  SelectionAll,
  Sparkle,
  Stack,
  Tag,
  Trash,
  UserCircle,
  UsersThree,
  Warning,
  X,
} from "@phosphor-icons/react";

const cover = "/assets/fallback-book-cover-v1.png";

const initialBooks = [
  { id: "three-body", title: "三体", author: "刘慈欣", type: "电子书", status: "进行中", tags: ["科幻", "中国文学"], series: "地球往事", publisher: "重庆出版社", language: "中文", year: "2008", format: "EPUB", progress: 37 },
  { id: "wandering-earth", title: "流浪地球", author: "刘慈欣", type: "电子书", status: "未开始", tags: ["科幻", "短篇"], series: "", publisher: "长江文艺出版社", language: "中文", year: "2017", format: "EPUB", progress: 0 },
  { id: "foundation", title: "基地", author: "艾萨克·阿西莫夫", type: "电子书", status: "进行中", tags: ["科幻", "太空歌剧"], series: "基地系列", publisher: "江苏凤凰文艺出版社", language: "中文", year: "2015", format: "EPUB", progress: 62 },
  { id: "dune", title: "沙丘", author: "弗兰克·赫伯特", type: "电子书", status: "已完成", tags: ["科幻", "太空歌剧"], series: "沙丘系列", publisher: "江苏凤凰文艺出版社", language: "中文", year: "2017", format: "EPUB", progress: 100 },
  { id: "sapiens", title: "人类简史", author: "尤瓦尔·赫拉利", type: "电子书", status: "未开始", tags: ["历史", "社会"], series: "", publisher: "中信出版社", language: "中文", year: "2014", format: "PDF", progress: 0 },
  { id: "night-watch", title: "守夜人", author: "特里·普拉切特", type: "有声书", status: "进行中", tags: ["奇幻", "幽默"], series: "碟形世界", publisher: "", language: "中文", year: "", format: "MP3", progress: 21 },
  { id: "akira", title: "阿基拉 01", author: "大友克洋", type: "漫画", status: "未开始", tags: ["漫画", "科幻"], series: "阿基拉", publisher: "讲谈社", language: "日文", year: "1982", format: "CBZ", progress: 0 },
  { id: "mobile-reading", title: "移动阅读体验测试集", author: "二毛图书", type: "电子书", status: "已完成", tags: ["测试", "移动端"], series: "", publisher: "", language: "中文", year: "2026", format: "EPUB", progress: 100 },
];

const initialCategories = {
  authors: [
    { id: "liu", name: "刘慈欣", count: 2, aliases: ["Cixin Liu"] },
    { id: "liu-traditional", name: "劉慈欣", count: 1, aliases: [] },
    { id: "asimov", name: "艾萨克·阿西莫夫", count: 1, aliases: ["Isaac Asimov"] },
    { id: "herbert", name: "弗兰克·赫伯特", count: 1, aliases: [] },
  ],
  tags: [
    { id: "sf", name: "科幻", count: 5, aliases: [] },
    { id: "sf-novel", name: "科幻小说", count: 2, aliases: [] },
    { id: "space-opera", name: "太空歌剧", count: 2, aliases: [] },
    { id: "testing", name: "测试", count: 1, aliases: [] },
  ],
  series: [
    { id: "earth", name: "地球往事", count: 1, aliases: [] },
    { id: "foundation", name: "基地系列", count: 1, aliases: [] },
    { id: "dune", name: "沙丘系列", count: 1, aliases: [] },
  ],
  publishers: [
    { id: "cq", name: "重庆出版社", count: 1, aliases: [] },
    { id: "js", name: "江苏凤凰文艺出版社", count: 2, aliases: [] },
    { id: "citic", name: "中信出版社", count: 1, aliases: [] },
  ],
};

const filterOptions = {
  types: ["电子书", "漫画", "有声书"],
  statuses: ["未开始", "进行中", "已完成"],
  tags: ["科幻", "太空歌剧", "历史", "漫画", "测试"],
};

function cx(...values) {
  return values.filter(Boolean).join(" ");
}

function IconButton({ label, children, active = false, onClick }) {
  return <button type="button" className={cx("icon-button", active && "is-active")} aria-label={label} title={label} onClick={onClick}>{children}</button>;
}

function Button({ children, icon: Icon, tone = "default", className = "", disabled = false, onClick, type = "button" }) {
  return <button type={type} className={cx("button", `button-${tone}`, className)} disabled={disabled} onClick={onClick}>{Icon ? <Icon size={18} weight="bold" /> : null}{children}</button>;
}

function Pill({ children, tone = "default" }) {
  return <span className={cx("pill", `pill-${tone}`)}>{children}</span>;
}

function Modal({ title, subtitle, wide = false, onClose, children, footer }) {
  return (
    <div className="overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose?.(); }}>
      <section className={cx("modal", wide && "modal-wide")} role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal-header">
          <div><h2>{title}</h2>{subtitle ? <p>{subtitle}</p> : null}</div>
          {onClose ? <IconButton label="关闭" onClick={onClose}><X size={20} /></IconButton> : null}
        </header>
        <div className="modal-body">{children}</div>
        {footer ? <footer className="modal-footer">{footer}</footer> : null}
      </section>
    </div>
  );
}

function EmptyState({ icon: Icon = Books, title, body, action }) {
  return <div className="empty-state"><Icon size={36} /><h3>{title}</h3><p>{body}</p>{action}</div>;
}

function BookCard({ book, selectable, selected, onToggle, onOpen }) {
  return (
    <article className={cx("book-card", selected && "is-selected")}>
      {selectable ? <button className="book-check" aria-label={`选择 ${book.title}`} onClick={() => onToggle(book.id)}><span className={cx("check-box", selected && "checked")}>{selected ? <Check size={14} weight="bold" /> : null}</span></button> : null}
      <button type="button" className="book-open" onClick={() => selectable ? onToggle(book.id) : onOpen(book)}>
        <img src={cover} alt="" className="book-cover" />
        <span className="book-copy">
          <strong>{book.title}</strong>
          <small>{book.author}</small>
          <span className="book-pills"><Pill>{book.type}</Pill><Pill tone={book.status === "进行中" ? "amber" : book.status === "已完成" ? "green" : "default"}>{book.status}</Pill></span>
          {book.progress > 0 ? <span className="progress-row"><span className="progress-track"><span style={{ width: `${book.progress}%` }} /></span><small>{book.progress}%</small></span> : null}
        </span>
      </button>
    </article>
  );
}

function FilterDrawer({ draft, setDraft, counts, onApply, onClose }) {
  function toggle(group, value) {
    setDraft((current) => ({ ...current, [group]: current[group].includes(value) ? current[group].filter((item) => item !== value) : [...current[group], value] }));
  }

  return (
    <div className="drawer-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <aside className="filter-drawer" aria-label="更多筛选">
        <header className="drawer-header"><div><h2>更多筛选</h2><p>不同分类之间同时满足</p></div><IconButton label="关闭筛选" onClick={onClose}><X size={20} /></IconButton></header>
        <div className="drawer-content">
          <Facet title="媒介类型" options={filterOptions.types} selected={draft.types} onToggle={(value) => toggle("types", value)} />
          <Facet title="阅读状态" options={filterOptions.statuses} selected={draft.statuses} onToggle={(value) => toggle("statuses", value)} />
          <Facet title="标签" options={filterOptions.tags} selected={draft.tags} onToggle={(value) => toggle("tags", value)} showCount />
          <div className="facet-summary"><Sparkle size={18} /><span>当前条件预计找到 <strong>{counts}</strong> 本图书</span></div>
        </div>
        <footer className="drawer-footer"><Button tone="ghost" onClick={() => setDraft({ types: [], statuses: [], tags: [] })}>清空</Button><Button tone="primary" onClick={onApply}>查看 {counts} 本图书</Button></footer>
      </aside>
    </div>
  );
}

function Facet({ title, options, selected, onToggle, showCount = false }) {
  return <section className="facet"><h3>{title}</h3><div className="facet-list">{options.map((option, index) => <button key={option} type="button" className={cx("facet-option", selected.includes(option) && "selected")} onClick={() => onToggle(option)}><span className="check-box">{selected.includes(option) ? <Check size={14} weight="bold" /> : null}</span><span>{option}</span>{showCount ? <small>{Math.max(1, 5 - index)}</small> : null}</button>)}</div></section>;
}

function BatchTagsModal({ selectedBooks, onClose, onApply }) {
  const [step, setStep] = useState("edit");
  const [tagName, setTagName] = useState("待读");
  const examples = selectedBooks.slice(0, 3);
  return (
    <Modal title={step === "done" ? "批量操作完成" : "批量添加标签"} subtitle={step === "done" ? "所选图书已经更新" : `将处理 ${selectedBooks.length} 本图书`} onClose={onClose} footer={step === "edit" ? <><Button tone="ghost" onClick={onClose}>取消</Button><Button tone="primary" onClick={() => setStep("preview")}>预览变化</Button></> : step === "preview" ? <><Button tone="ghost" icon={ArrowLeft} onClick={() => setStep("edit")}>返回</Button><Button tone="primary" onClick={() => { onApply(tagName); setStep("done"); }}>确认添加</Button></> : <Button tone="primary" onClick={onClose}>返回书库</Button>}>
      {step === "edit" ? <div className="form-stack"><label>添加标签<input value={tagName} onChange={(event) => setTagName(event.target.value)} /></label><div className="quick-options">{["待读", "待重读", "收藏"].map((tagItem) => <button key={tagItem} type="button" onClick={() => setTagName(tagItem)}>{tagItem}</button>)}</div><p className="helper">已有同名标签的图书不会重复添加。</p></div> : null}
      {step === "preview" ? <div className="preview-block"><div className="impact-row"><span>将发生变化</span><strong>{selectedBooks.filter((book) => !book.tags.includes(tagName)).length} 本</strong></div><div className="impact-row"><span>无需变化</span><strong>{selectedBooks.filter((book) => book.tags.includes(tagName)).length} 本</strong></div><h3>变化示例</h3>{examples.map((book) => <div className="change-row" key={book.id}><img src={cover} alt="" /><span><strong>{book.title}</strong><small>{book.tags.join(" · ")} → {book.tags.includes(tagName) ? "无变化" : `${book.tags.join(" · ")} · ${tagName}`}</small></span></div>)}</div> : null}
      {step === "done" ? <div className="success-panel"><CheckCircle size={48} weight="fill" /><h3>已为 {selectedBooks.length} 本图书添加“{tagName}”</h3><p>操作记录将在 7 天内提供撤销。</p></div> : null}
    </Modal>
  );
}

function SmartShelfModal({ filters, onClose, onSave }) {
  const [name, setName] = useState("未读科幻");
  const summary = [filters.types.join("或"), filters.statuses.join("或"), filters.tags.join("或")].filter(Boolean).join(" · ") || "全部图书";
  return <Modal title="保存为智能书架" subtitle="书架会随着图书信息自动更新" onClose={onClose} footer={<><Button tone="ghost" onClick={onClose}>取消</Button><Button tone="primary" disabled={!name.trim()} onClick={() => onSave({ name, summary })}>保存书架</Button></>}><div className="form-stack"><label>书架名称<input value={name} onChange={(event) => setName(event.target.value)} /></label><div className="rule-card"><Funnel size={20} /><span><small>自动收录规则</small><strong>{summary}</strong></span></div><label className="switch-row"><span>显示在侧边栏</span><input type="checkbox" defaultChecked /></label></div></Modal>;
}

function DuplicateFlow({ onClose, onResolved }) {
  const [step, setStep] = useState("compare");
  const [primary, setPrimary] = useState("three-body");
  const candidate = initialBooks[0];
  return (
    <Modal wide title={step === "success" ? "合并完成" : "检查重复作品"} subtitle={step === "compare" ? "选择保留的主作品，并检查内容差异" : step === "preview" ? "确认合并后的作品结构" : "旧作品关系已经安全迁移"} onClose={onClose} footer={step === "compare" ? <><Button tone="ghost" onClick={onClose}>稍后处理</Button><Button tone="primary" onClick={() => setStep("preview")}>预览合并</Button></> : step === "preview" ? <><Button tone="ghost" icon={ArrowLeft} onClick={() => setStep("compare")}>返回比较</Button><Button tone="primary" icon={ArrowsMerge} onClick={() => { onResolved(); setStep("success"); }}>确认合并</Button></> : <><Button tone="ghost" icon={ClockCounterClockwise}>撤销合并</Button><Button tone="primary" onClick={onClose}>打开合并后的图书</Button></>}>
      {step === "compare" ? <div className="duplicate-compare">
        {[{ id: "three-body", title: "三体", meta: "刘慈欣 · EPUB · 重庆出版社", badges: ["主版本", "进度 37%"] }, { id: "three-body-copy", title: "三体全集", meta: "劉慈欣 · PDF · 未知出版社", badges: ["后备版本", "加入书架：科幻"] }].map((item) => <button type="button" key={item.id} className={cx("candidate-card", primary === item.id && "selected")} onClick={() => setPrimary(item.id)}><span className="radio-dot">{primary === item.id ? <span /> : null}</span><img src={cover} alt="" /><span><strong>{item.title}</strong><small>{item.meta}</small><span className="book-pills">{item.badges.map((badge) => <Pill key={badge}>{badge}</Pill>)}</span></span></button>)}
        <section className="merge-rules"><h3>默认处理</h3><ul><li>标题和作者使用所选主作品</li><li>EPUB 与 PDF 都保留为版本</li><li>标签和普通书架合并去重</li><li>原始文件不会被删除</li></ul></section>
      </div> : null}
      {step === "preview" ? <div className="structure-preview"><div className="warning-note"><Warning size={20} /><span>将把 2 条作品记录合并为 1 条，原始文件位置不变。</span></div><h3>{primary === "three-body" ? "三体" : "三体全集"}</h3><div className="tree-row"><BookOpenText size={20} /><span><strong>电子书</strong><small>EPUB 主版本 · PDF 后备版本</small></span></div><div className="tree-row"><Tag size={20} /><span><strong>标签与书架</strong><small>科幻、中国文学 · 科幻书架</small></span></div><div className="tree-row"><ClockCounterClockwise size={20} /><span><strong>阅读进度</strong><small>保留 EPUB 最近位置 37%</small></span></div></div> : null}
      {step === "success" ? <div className="success-panel"><CheckCircle size={48} weight="fill" /><h3>作品已合并，两个版本均已保留</h3><p>7 天内且内容结构未再次变化时可以撤销。</p></div> : null}
    </Modal>
  );
}

function CategoryManager({ categories, setCategories, onToast }) {
  const [type, setType] = useState("authors");
  const [selected, setSelected] = useState([]);
  const [mergeOpen, setMergeOpen] = useState(false);
  const labels = { authors: "作者", tags: "标签", series: "系列", publishers: "出版社" };
  const rows = categories[type];
  function toggle(id) { setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]); }
  function applyMerge() {
    const canonical = rows.find((row) => row.id === selected[0]);
    const removed = rows.filter((row) => selected.includes(row.id) && row.id !== canonical.id);
    setCategories((current) => ({ ...current, [type]: current[type].filter((row) => !removed.some((item) => item.id === row.id)).map((row) => row.id === canonical.id ? { ...row, count: selected.reduce((sum, id) => sum + (rows.find((item) => item.id === id)?.count || 0), 0), aliases: [...row.aliases, ...removed.map((item) => item.name)] } : row) }));
    setSelected([]); setMergeOpen(false); onToast(`已合并 ${removed.length + 1} 个${labels[type]}`);
  }
  return <div className="manager-panel"><div className="section-head"><div><h2>分类管理</h2><p>统一同义、错字和重复命名。</p></div><div className="manager-actions"><Button tone="ghost" icon={PencilSimple} disabled={selected.length !== 1}>重命名</Button><Button tone="primary" icon={ArrowsMerge} disabled={selected.length < 2} onClick={() => setMergeOpen(true)}>合并</Button></div></div><div className="subtabs">{Object.entries(labels).map(([key, value]) => <button type="button" key={key} className={cx(type === key && "active")} onClick={() => { setType(key); setSelected([]); }}>{value}</button>)}</div><div className="category-table"><div className="table-row table-head"><span></span><span>规范名称</span><span>图书</span><span>别名</span><span></span></div>{rows.map((row) => <div className="table-row" key={row.id}><button type="button" className="plain-check" aria-label={`${selected.includes(row.id) ? "取消选择" : "选择"} ${row.name}`} title={`${selected.includes(row.id) ? "取消选择" : "选择"} ${row.name}`} onClick={() => toggle(row.id)}><span className={cx("check-box", selected.includes(row.id) && "checked")}>{selected.includes(row.id) ? <Check size={14} /> : null}</span></button><span><strong>{row.name}</strong>{row.id.includes("traditional") || row.id.includes("novel") ? <small className="possible-duplicate">可能重复</small> : null}</span><span>{row.count}</span><span>{row.aliases.length}</span><IconButton label={`打开 ${row.name}`}><CaretRight size={18} /></IconButton></div>)}</div>{mergeOpen ? <Modal title={`合并${labels[type]}`} subtitle={`将 ${selected.length} 个项目统一到一个规范名称`} onClose={() => setMergeOpen(false)} footer={<><Button tone="ghost" onClick={() => setMergeOpen(false)}>取消</Button><Button tone="primary" onClick={applyMerge}>确认合并</Button></>}><div className="form-stack"><label>保留为规范项<select defaultValue={selected[0]}>{rows.filter((row) => selected.includes(row.id)).map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label><div className="rule-card"><ArrowsMerge size={20} /><span><small>影响范围</small><strong>{selected.reduce((sum, id) => sum + (rows.find((row) => row.id === id)?.count || 0), 0)} 本图书 · 智能书架规则自动迁移</strong></span></div><p className="helper">其他名称会保留为搜索别名，操作可在 7 天内撤销。</p></div></Modal> : null}</div>;
}

function BookDetailFlow({ book, onClose, onSave, onToast }) {
  const [mode, setMode] = useState("view");
  const [tab, setTab] = useState("work");
  const [draft, setDraft] = useState({ ...book, isbn: "9787536692930", publishedAt: `${book.year || "2026"}-01-01` });
  const [splitStep, setSplitStep] = useState("choose");
  if (!book) return null;
  function save() { onSave(draft); onToast("图书信息已保存"); setMode("view"); }
  if (mode === "metadata") return <Modal wide title="编辑图书信息" subtitle={`维护《${book.title}》的作品信息与版本出版信息`} onClose={() => setMode("view")} footer={<><Button tone="ghost" onClick={() => setMode("view")}>取消</Button><Button tone="primary" onClick={save}>保存信息</Button></>}><div className="subtabs editor-tabs"><button type="button" className={cx(tab === "work" && "active")} onClick={() => setTab("work")}>作品信息</button><button type="button" className={cx(tab === "edition" && "active")} onClick={() => setTab("edition")}>版本信息</button></div>{tab === "work" ? <div className="form-grid"><label>标题<input value={draft.title} onChange={(event) => setDraft({ ...draft, title: event.target.value })} /></label><label>作者<div className="token-input"><span>{draft.author}<button type="button" aria-label="移除作者"><X size={12} /></button></span><input placeholder="添加作者" /></div></label><label>系列<input value={draft.series} onChange={(event) => setDraft({ ...draft, series: event.target.value })} /></label><label>标签<input value={draft.tags.join("，")} onChange={(event) => setDraft({ ...draft, tags: event.target.value.split(/[，,]/).map((item) => item.trim()).filter(Boolean) })} /></label><label className="full">简介<textarea rows="5" defaultValue="一部已经加入书库的示例作品，用于演示完整元数据编辑流程。" /></label><Button tone="soft" icon={Sparkle} className="full">从数据源补全到草稿</Button></div> : <div className="form-grid"><label>版本<select defaultValue="epub"><option value="epub">EPUB 主版本</option><option value="pdf">PDF 后备版本</option></select></label><label>出版社<input value={draft.publisher} onChange={(event) => setDraft({ ...draft, publisher: event.target.value })} /></label><label>出版日期<input type="date" value={draft.publishedAt} onChange={(event) => setDraft({ ...draft, publishedAt: event.target.value })} /></label><label>语言<select value={draft.language} onChange={(event) => setDraft({ ...draft, language: event.target.value })}><option>中文</option><option>英文</option><option>日文</option></select></label><label className="full">ISBN<input value={draft.isbn} onChange={(event) => setDraft({ ...draft, isbn: event.target.value })} /></label><div className="read-only-row full"><span>格式与来源</span><strong>{draft.format} · /monitor/books/{draft.id}.{draft.format.toLowerCase()}</strong></div></div>}</Modal>;
  if (mode === "structure") return <Modal wide title="管理内容结构" subtitle="调整主版本，或把错误合并的内容拆分出去" onClose={() => setMode("view")} footer={<Button tone="ghost" onClick={() => setMode("view")}>返回详情</Button>}><div className="version-list"><div className="version-row"><BookOpenText size={24} /><span><strong>EPUB 主版本</strong><small>12 章 · 阅读进度 {book.progress}%</small></span><Pill tone="amber">主版本</Pill></div><div className="version-row"><BookOpenText size={24} /><span><strong>PDF 后备版本</strong><small>428 页 · 来自重复合并</small></span><Button tone="ghost" onClick={() => { setMode("split"); setSplitStep("choose"); }}>拆分</Button></div></div></Modal>;
  if (mode === "split") return <Modal wide title={splitStep === "done" ? "拆分完成" : "拆分内容"} subtitle={splitStep === "choose" ? "选择要移出的版本，并确认新作品信息" : splitStep === "preview" ? "同时检查拆分后的两个作品" : "原始文件位置没有变化"} onClose={() => setMode("structure")} footer={splitStep === "choose" ? <><Button tone="ghost" onClick={() => setMode("structure")}>取消</Button><Button tone="primary" onClick={() => setSplitStep("preview")}>预览拆分</Button></> : splitStep === "preview" ? <><Button tone="ghost" onClick={() => setSplitStep("choose")}>返回</Button><Button tone="primary" onClick={() => setSplitStep("done")}>确认拆分</Button></> : <Button tone="primary" onClick={onClose}>打开新作品</Button>}>
    {splitStep === "choose" ? <div className="form-stack"><div className="selected-version"><span className="check-box checked"><Check size={14} /></span><BookOpenText size={24} /><span><strong>PDF 后备版本</strong><small>428 页 · 文件跟随版本移动</small></span></div><label>新作品标题<input defaultValue={`${book.title}（PDF 版）`} /></label><label>作者<input defaultValue={book.author} /></label><p className="helper">普通书架默认同时保留源作品和新作品，阅读进度随版本移动。</p></div> : null}
    {splitStep === "preview" ? <div className="split-preview"><section><small>源作品</small><h3>{book.title}</h3><p>保留 EPUB 主版本 · {book.progress}%</p></section><CaretRight size={24} /><section><small>新作品</small><h3>{book.title}（PDF 版）</h3><p>包含 PDF 后备版本 · 428 页</p></section></div> : null}
    {splitStep === "done" ? <div className="success-panel"><CheckCircle size={48} weight="fill" /><h3>PDF 版本已拆分为独立作品</h3><p>书架关系与版本数据已迁移，原始文件没有移动。</p></div> : null}
  </Modal>;
  return <Modal wide title={book.title} subtitle={`${book.author} · ${book.type} · ${book.format}`} onClose={onClose} footer={<><Button tone="ghost" icon={PencilSimple} onClick={() => setMode("metadata")}>编辑信息</Button><Button tone="primary" icon={BookOpenText}>继续阅读</Button></>}><div className="detail-layout"><img src={cover} alt="" /><div><div className="book-pills"><Pill>{book.type}</Pill><Pill tone="amber">{book.status}</Pill>{book.tags.map((tagItem) => <Pill key={tagItem}>{tagItem}</Pill>)}</div><h3>作品信息</h3><dl><div><dt>出版社</dt><dd>{book.publisher || "未填写"}</dd></div><div><dt>语言</dt><dd>{book.language || "未填写"}</dd></div><div><dt>系列</dt><dd>{book.series || "未归入系列"}</dd></div></dl><Button tone="soft" icon={Stack} onClick={() => setMode("structure")}>管理内容结构</Button></div></div></Modal>;
}

export function App() {
  const [route, setRoute] = useState("library");
  const [books, setBooks] = useState(initialBooks);
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState({ types: [], statuses: [], tags: [] });
  const [filterDraft, setFilterDraft] = useState(filters);
  const [filterOpen, setFilterOpen] = useState(false);
  const [selectionMode, setSelectionMode] = useState(false);
  const [selected, setSelected] = useState([]);
  const [view, setView] = useState("grid");
  const [batchTagsOpen, setBatchTagsOpen] = useState(false);
  const [smartOpen, setSmartOpen] = useState(false);
  const [smartShelves, setSmartShelves] = useState([{ id: "smart-sf", name: "未读科幻", summary: "未开始 · 科幻", count: 2 }]);
  const [organizeTab, setOrganizeTab] = useState("duplicates");
  const [duplicateOpen, setDuplicateOpen] = useState(false);
  const [duplicateResolved, setDuplicateResolved] = useState(false);
  const [categories, setCategories] = useState(initialCategories);
  const [detailBook, setDetailBook] = useState(null);
  const [toast, setToast] = useState("");

  const filteredBooks = useMemo(() => books.filter((book) => {
    const term = search.trim().toLowerCase();
    if (term && ![book.title, book.author, ...book.tags].join(" ").toLowerCase().includes(term)) return false;
    if (filters.types.length && !filters.types.includes(book.type)) return false;
    if (filters.statuses.length && !filters.statuses.includes(book.status)) return false;
    if (filters.tags.length && !filters.tags.some((tagItem) => book.tags.includes(tagItem))) return false;
    return true;
  }), [books, filters, search]);

  const draftCount = useMemo(() => books.filter((book) => (!filterDraft.types.length || filterDraft.types.includes(book.type)) && (!filterDraft.statuses.length || filterDraft.statuses.includes(book.status)) && (!filterDraft.tags.length || filterDraft.tags.some((tagItem) => book.tags.includes(tagItem)))).length, [books, filterDraft]);
  const selectedBooks = books.filter((book) => selected.includes(book.id));
  const filterChips = [...filters.types, ...filters.statuses, ...filters.tags];

  function notify(message) { setToast(message); window.setTimeout(() => setToast(""), 2600); }
  function toggleSelected(id) { setSelected((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id]); }
  function leaveSelection() { setSelectionMode(false); setSelected([]); }
  function navigate(next) { setRoute(next); leaveSelection(); }
  function applyBatchTag(tagName) { setBooks((current) => current.map((book) => selected.includes(book.id) && !book.tags.includes(tagName) ? { ...book, tags: [...book.tags, tagName] } : book)); }
  function saveBook(next) { setBooks((current) => current.map((book) => book.id === next.id ? next : book)); setDetailBook(next); }
  function openSmartShelf(shelf) { setFilters({ types: [], statuses: ["未开始"], tags: ["科幻"] }); setSearch(""); navigate("library"); notify(`已打开智能书架“${shelf.name}”`); }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand"><img src="/assets/ermao-library-app-icon-v1.png" alt="" /><span><strong>二毛图书</strong><small>我的数字书库</small></span></div>
        <nav className="main-nav" aria-label="主导航">
          <button type="button" className={cx(route === "home" && "active")} onClick={() => navigate("home")}><House size={20} />首页</button>
          <button type="button" className={cx(route === "library" && "active")} onClick={() => navigate("library")}><Books size={20} />全部图书</button>
          <button type="button" className={cx(route === "shelves" && "active")} onClick={() => navigate("shelves")}><Stack size={20} />书架</button>
        </nav>
        <div className="sidebar-section"><small>智能书架</small>{smartShelves.map((shelf) => <button type="button" key={shelf.id} onClick={() => openSmartShelf(shelf)}><Sparkle size={18} />{shelf.name}<span>{shelf.count}</span></button>)}</div>
        <button type="button" className={cx("settings-entry", route === "organize" && "active")} onClick={() => navigate("organize")}><UserCircle size={28} weight="fill" /><span><strong>我的设置</strong><small>书库整理</small></span><CaretRight size={17} /></button>
      </aside>

      <main className="content">
        {route === "home" ? <Home books={books} onOpen={setDetailBook} onLibrary={() => navigate("library")} /> : null}
        {route === "library" ? <>
          <header className="page-header"><div><h1>全部图书</h1><span>{filteredBooks.length} 本</span></div><Button icon={Plus} tone="outline">导入图书</Button></header>
          <div className="library-toolbar"><label className="search-field"><MagnifyingGlass size={19} /><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索书名、作者或标签" /></label><Button tone={filterChips.length ? "soft" : "outline"} icon={Funnel} onClick={() => { setFilterDraft(filters); setFilterOpen(true); }}>更多筛选{filterChips.length ? ` · ${filterChips.length}` : ""}</Button><Button tone={selectionMode ? "soft" : "outline"} icon={CheckSquare} onClick={() => selectionMode ? leaveSelection() : setSelectionMode(true)}>{selectionMode ? "完成" : "选择"}</Button><div className="view-toggle"><IconButton label="网格" active={view === "grid"} onClick={() => setView("grid")}><GridFour size={19} /></IconButton><IconButton label="列表" active={view === "list"} onClick={() => setView("list")}><List size={19} /></IconButton></div></div>
          {filterChips.length ? <div className="active-filters">{filterChips.map((chip) => <button type="button" key={chip} onClick={() => setFilters((current) => ({ types: current.types.filter((item) => item !== chip), statuses: current.statuses.filter((item) => item !== chip), tags: current.tags.filter((item) => item !== chip) }))}>{chip}<X size={13} /></button>)}<button type="button" className="save-smart" onClick={() => setSmartOpen(true)}><Sparkle size={15} />保存为智能书架</button></div> : null}
          {selectionMode ? <div className="selection-summary"><span>已选 <strong>{selected.length}</strong> 本</span><button type="button" onClick={() => setSelected(filteredBooks.map((book) => book.id))}><SelectionAll size={17} />选择全部 {filteredBooks.length} 个结果</button></div> : null}
          {filteredBooks.length ? <section className={cx("book-grid", view === "list" && "list-view")}>{filteredBooks.map((book) => <BookCard key={book.id} book={book} selectable={selectionMode} selected={selected.includes(book.id)} onToggle={toggleSelected} onOpen={setDetailBook} />)}</section> : <EmptyState title="没有符合条件的图书" body="撤销一个筛选条件，或清空全部筛选后再试。" action={<Button tone="soft" onClick={() => setFilters({ types: [], statuses: [], tags: [] })}>清空筛选</Button>} />}
          {selected.length ? <div className="batch-bar"><span><CheckSquare size={20} weight="fill" />已选 {selected.length} 本</span><Button tone="ghost" icon={Stack} onClick={() => notify("选择书架后将先展示影响预览")}>书架</Button><Button tone="ghost" icon={Tag} onClick={() => setBatchTagsOpen(true)}>标签</Button><Button tone="ghost" icon={CheckCircle} onClick={() => notify("阅读状态操作会先选择作用媒介")}>状态</Button><Button tone="ghost" icon={PencilSimple} onClick={() => notify("批量编辑支持仅补空值、覆盖和清空")}>编辑信息</Button><IconButton label="更多操作"><DotsThree size={22} /></IconButton></div> : null}
        </> : null}
        {route === "shelves" ? <Shelves smartShelves={smartShelves} onCreate={() => setSmartOpen(true)} onOpen={openSmartShelf} /> : null}
        {route === "organize" ? <OrganizeScreen active={organizeTab} setActive={setOrganizeTab} duplicateResolved={duplicateResolved} onDuplicate={() => setDuplicateOpen(true)} categories={categories} setCategories={setCategories} onToast={notify} /> : null}
      </main>

      <nav className="mobile-nav" aria-label="移动导航"><button type="button" className={cx(route === "home" && "active")} onClick={() => navigate("home")}><House size={22} /><span>首页</span></button><button type="button" className={cx(route === "library" && "active")} onClick={() => navigate("library")}><Books size={22} /><span>全部</span></button><button type="button" className={cx(route === "shelves" && "active")} onClick={() => navigate("shelves")}><Stack size={22} /><span>书架</span></button><button type="button" className={cx(route === "organize" && "active")} onClick={() => navigate("organize")}><Gear size={22} /><span>我的</span></button></nav>

      {filterOpen ? <FilterDrawer draft={filterDraft} setDraft={setFilterDraft} counts={draftCount} onClose={() => setFilterOpen(false)} onApply={() => { setFilters(filterDraft); setFilterOpen(false); }} /> : null}
      {batchTagsOpen ? <BatchTagsModal selectedBooks={selectedBooks} onApply={applyBatchTag} onClose={() => { setBatchTagsOpen(false); leaveSelection(); }} /> : null}
      {smartOpen ? <SmartShelfModal filters={filters} onClose={() => setSmartOpen(false)} onSave={({ name, summary }) => { const next = { id: `smart-${Date.now()}`, name, summary, count: filteredBooks.length }; setSmartShelves((current) => [...current, next]); setSmartOpen(false); notify(`已创建智能书架“${name}”`); }} /> : null}
      {duplicateOpen ? <DuplicateFlow onResolved={() => setDuplicateResolved(true)} onClose={() => setDuplicateOpen(false)} /> : null}
      {detailBook ? <BookDetailFlow book={detailBook} onClose={() => setDetailBook(null)} onSave={saveBook} onToast={notify} /> : null}
      {toast ? <div className="toast"><CheckCircle size={19} weight="fill" />{toast}</div> : null}
    </div>
  );
}

function Home({ books, onOpen, onLibrary }) {
  return <><header className="page-header"><div><h1>晚上好</h1><p>从上次停下的地方继续。</p></div></header><section className="continue-card"><img src={cover} alt="" /><div><Pill tone="amber">继续阅读</Pill><h2>{books[0].title}</h2><p>{books[0].author} · 第 5 章</p><div className="progress-row"><span className="progress-track"><span style={{ width: `${books[0].progress}%` }} /></span><small>{books[0].progress}%</small></div><Button tone="primary" icon={BookOpenText} onClick={() => onOpen(books[0])}>继续阅读</Button></div></section><div className="section-head"><div><h2>最近加入</h2><p>刚进入书库的读物</p></div><Button tone="ghost" onClick={onLibrary}>查看全部</Button></div><section className="book-grid compact">{books.slice(0, 4).map((book) => <BookCard key={book.id} book={book} onOpen={onOpen} />)}</section></>;
}

function Shelves({ smartShelves, onCreate, onOpen }) {
  const staticShelves = [{ id: "summer", name: "今年夏天读完", body: "4 本 · 阅读计划", smart: false }, { id: "favorites", name: "值得重读", body: "7 本 · 收藏", smart: false }];
  return <><header className="page-header"><div><h1>书架</h1><p>普通书架手动整理，智能书架按规则自动更新。</p></div><Button tone="primary" icon={Plus} onClick={onCreate}>新建书架</Button></header><section className="shelf-grid">{staticShelves.map((shelf) => <article className="shelf-card" key={shelf.id}><Stack size={28} /><div><Pill>普通书架</Pill><h2>{shelf.name}</h2><p>{shelf.body}</p></div><IconButton label={`打开 ${shelf.name}`}><CaretRight size={19} /></IconButton></article>)}{smartShelves.map((shelf) => <button type="button" className="shelf-card smart" key={shelf.id} onClick={() => onOpen(shelf)}><Sparkle size={28} weight="fill" /><div><Pill tone="amber">智能书架</Pill><h2>{shelf.name}</h2><p>{shelf.count} 本 · {shelf.summary}</p></div><CaretRight size={19} /></button>)}</section></>;
}

function OrganizeScreen({ active, setActive, duplicateResolved, onDuplicate, categories, setCategories, onToast }) {
  const tabs = [{ key: "queue", label: "整理队列" }, { key: "duplicates", label: "重复项" }, { key: "categories", label: "分类管理" }, { key: "recognition", label: "识别设置" }];
  return <><header className="page-header"><div><h1>书库整理</h1><p>处理重复内容、统一分类和元数据。</p></div></header><div className="settings-tabs">{tabs.map((tab) => <button type="button" key={tab.key} className={cx(active === tab.key && "active")} onClick={() => setActive(tab.key)}>{tab.label}{tab.key === "duplicates" && !duplicateResolved ? <span>1</span> : null}</button>)}</div>{active === "duplicates" ? <div className="manager-panel"><div className="section-head"><div><h2>重复项</h2><p>系统只提供候选，合并前由你确认。</p></div><Button tone="outline" icon={ClockCounterClockwise}>重新扫描</Button></div>{duplicateResolved ? <EmptyState icon={CheckCircle} title="没有待确认的重复作品" body="最近一次扫描没有发现新的候选。" /> : <article className="duplicate-row"><img src={cover} alt="" /><div><div className="book-pills"><Pill tone="amber">高置信度</Pill><Pill>标题与作者相似</Pill></div><h3>《三体》可能有 2 条作品记录</h3><p>EPUB 与 PDF · 2 个来源 · 标签和进度存在差异</p></div><Button tone="primary" onClick={onDuplicate}>检查并处理</Button></article>}</div> : null}{active === "categories" ? <CategoryManager categories={categories} setCategories={setCategories} onToast={onToast} /> : null}{active === "queue" ? <div className="manager-panel"><div className="section-head"><div><h2>整理队列</h2><p>按当前识别策略处理缺失元数据。</p></div></div><article className="queue-row"><img src={cover} alt="" /><div><h3>守夜人</h3><p>缺少出版社和出版日期</p></div><Pill tone="amber">等待识别</Pill><Button tone="ghost">重新识别</Button></article></div> : null}{active === "recognition" ? <div className="manager-panel"><div className="section-head"><div><h2>识别设置</h2><p>控制新导入图书如何补全元数据。</p></div></div><label className="setting-row"><span><strong>自动补全空字段</strong><small>标题、作者之外的已有信息不会被覆盖</small></span><input type="checkbox" defaultChecked /></label><label className="setting-row"><span><strong>覆盖已有标题和作者</strong><small>仅在匹配到唯一高置信度候选时应用</small></span><input type="checkbox" /></label></div> : null}</>;
}
