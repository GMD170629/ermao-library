# Reader controller redesign — Design QA

## Source truth

- Selected direction: Option 2, “thumb dock” (`拇指底部台`).
- Reference visual: `/mnt/c/Users/gamer/.codex/generated_images/019f7821-a97a-73f2-abc4-9ea71acf2451/exec-21e7da54-658e-4d5e-9ad2-d468df2bc4fe.png`.
- Required states: desktop EPUB with settings, iPad comic in a dark theme, and mobile EPUB with the compact bottom dock.
- Product constraints retained: the reader canvas stays stable while chrome appears; controls remain format-aware; 44px or larger touch targets; safe-area support; project amber/warm palette.

## Captured implementation

- Desktop EPUB, 1440×900: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-desktop-epub.png`
- iPad comic, 834×1112: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-ipad-comic.png`
- Mobile EPUB, 390×844: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-mobile-epub.png`
- Combined reference/implementation input: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-option-2-comparison.png`
- Responsive handoff sheet: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-option-2-responsive.png`

All implementation captures were generated from the running application with deterministic Playwright API fixtures. The comic artwork in the QA fixture is derived from the selected reference visual; it is not shipped as a production application asset.

## QA history

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 | Focusing a bottom control could programmatically scroll an `overflow-hidden` reader root, shifting both overlays upward by 44px. | Made the fixed reader root and its layout container non-scrollable with `overflow: clip`; recaptured all three viewports. |
| P1 | React emitted a console error for boolean `inert` attributes when a modal panel opened. | Emit the standards-compliant empty `inert` attribute only when required; visual capture now reports zero console errors. |
| P1 | Delayed iOS compatibility clicks could survive an EPUB iframe replacement and start navigation twice. | Added a one-shot compatibility-click guard that survives replacement and verified it on iPhone WebKit. |
| P2 | The first mobile dock pass was edge-to-edge and did not communicate the progress control hierarchy strongly enough. | Added horizontal breathing room, a floating rounded surface, and an amber circular primary treatment for Progress. |
| P2 | Comic and EPUB initially exposed the same action set. | EPUB/PDF keep text annotation access; comic omits text annotation while retaining TOC, bookmark, progress, and display controls. |

No unresolved P0, P1, or P2 findings remain in the inspected states.

## Functional and responsive coverage

- Desktop/tablet: inline previous/next navigation, chapter/page label, range scrubber, TOC, bookmark, annotation where supported, and settings.
- Mobile: five-action EPUB/PDF thumb dock; four-action comic dock; dedicated progress sheet with previous/next controls.
- Settings: EPUB themes, font size, line height, font family, page width, animation, and paginated/scrolled layout; comic mode, fit, quality, direction, zoom, and dark surface; PDF theme, zoom, and fit.
- Panels: modal focus trap, Escape dismissal, focus restoration, background inertness, safe-area coverage, and scroll containment.
- Inputs audited: keyboard navigation, pointer zones, touch tap/swipe, mobile iframe input, and hidden-control recovery.
- Bookmarking: current-position add/remove state, visible confirmation, and local persistence isolated by user, edition, volume, and content fingerprint.

## Verification

- TypeScript: passed.
- ESLint: passed with no warnings.
- Unit tests: 94 passed.
- Chromium reader E2E: 14 passed.
- iPhone WebKit reader E2E: 13 passed, 1 capability-gated skip.
- Standard WebKit reader E2E: 12 passed, 2 capability-gated skips.
- Visual capture suite: 5 passed with zero page console errors.

## Anchored panel refinement — 2026-07-19

### Comparison target and evidence

- Source visual truth: `/mnt/c/Users/gamer/.codex/generated_images/019f7821-a97a-73f2-abc4-9ea71acf2451/exec-21e7da54-658e-4d5e-9ad2-d468df2bc4fe.png`.
- User interaction specification: clicking the bottom TOC button must reveal the TOC immediately above that button, not at the right edge of the reader.
- Implementation screenshot: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-directory-anchored.png`.
- Full-view comparison input: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-directory-anchor-comparison.png`.
- Viewport: 1440×900.
- State: desktop EPUB, warm theme, reader controls visible, TOC open.
- The reference shows the same contextual-panel relationship using the Display button, while the implementation shows the requested TOC state. The difference in panel content is intentional; the placement rule is the comparison target.
- Focused evidence: the 1440×900 implementation capture keeps the panel and its triggering button large enough to inspect without another crop. The button center falls inside the panel bounds and the panel bottom sits 12px above the button.

### Comparison history

| Severity | Earlier finding | Fix | Post-fix evidence |
| --- | --- | --- | --- |
| P1 | Desktop TOC opened at the right edge, breaking the spatial relationship with the left-side TOC button. | Use the clicked dock button as the panel anchor; center the panel over it, keep a 12px vertical gap, and clamp the panel to a 20px viewport inset. | `reader-directory-anchor-comparison.png` shows the TOC directly above its button; Playwright verifies both vertical separation and horizontal containment. |
| P2 | A fixed desktop position would drift after viewport or panel-size changes. | Recalculate placement on window/visual-viewport resize and panel resize. | Tablet WebKit and Chromium coordinate checks pass; the panel remains within the viewport edge inset. |
| P2 | Applying the desktop popover geometry to phones would reduce usable TOC space. | Keep the existing full-width bottom sheet below the 768px breakpoint. | 390×844 Chromium and iPhone WebKit checks confirm a full-width mobile dialog. |

### Fidelity surfaces

- Fonts and typography: unchanged from the passed reader baseline; panel title, metadata, and chapter rows retain the project type scale and optical weight.
- Spacing and layout rhythm: changed only at the desktop/tablet panel anchor; 12px trigger gap and 20px edge inset are consistent and uncropped.
- Colors and visual tokens: warm surface, amber selected chapter, border, radius, and shadow tokens remain unchanged.
- Image quality and assets: no production imagery or icons were added or replaced.
- Copy and content: TOC labels and chapter hierarchy are unchanged.
- Interaction/accessibility: Escape dismissal, focus trap, focus restoration, background inertness, mobile bottom-sheet behavior, and zero console errors were verified.

### Refinement verification

- Chromium full reader E2E: 14 passed.
- Standard WebKit anchored-panel checks: 3 passed.
- iPhone WebKit responsive-panel checks: 3 passed after applying the mobile/desktop assertion branch.
- TypeScript, ESLint, and 94 unit tests: passed.
- No unresolved P0, P1, or P2 findings remain.

## Selected state, dismissal, and compact settings — 2026-07-19

### Comparison target and evidence

- Source visual truth: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-settings-before-compact.png`, together with the user's scoped requirements for inset selected states, four color-only theme choices, three font-size levels, three Word-style line-spacing levels, and compact treatment for every remaining setting.
- Implementation screenshots:
  - Tablet comic, 834×1112: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-settings-compact-tablet.png`.
  - Mobile EPUB, 390×844: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-settings-compact-mobile.png`.
- Full-view source/implementation comparison input: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-settings-compact-comparison.png`.
- States: warm theme; reader controls visible; settings open; tablet comic and mobile EPUB variants.
- Focused-region evidence: a separate crop was not needed because the combined 1748×1223 comparison preserves each 834×1112 capture at native scale, leaving the selected dock button, color swatches, setting rows, icons, and labels directly inspectable.

### Comparison history

| Severity | Earlier finding | Fix | Post-fix evidence |
| --- | --- | --- | --- |
| P1 | The dock's selected background filled the full button bounds and visually touched the controller perimeter. | Moved the selected surface into an inner rounded container with a 6px inset while preserving the full touch target. | Desktop coordinate assertions confirm at least 5px inset on both axes; the settings button in both new captures shows the intended breathing room. |
| P1 | The settings panel used large two-column tiles and occupied 448px of desktop width, making simple reading adjustments feel heavy. | Reduced the desktop settings width to 384px and converted all controls to compact single-row groups. | `reader-settings-compact-comparison.png` shows the panel changing from a 448×691 region to a 384×478 region without removing capabilities. |
| P2 | Theme choices repeated the word “主题” and four text-heavy tiles. | Replaced them with four accessible color circles; the selected circle uses an inset ring and check mark. | Tablet and mobile captures show four distinct surfaces with no visible “主题” label; Playwright verifies four named buttons. |
| P2 | Font size and line height required repeated plus/minus taps and exposed implementation values. | Replaced both with small/medium/large presets; line height uses Rows2/Rows3/Rows4 icons plus the three labels. | Mobile EPUB capture shows both three-choice rows and E2E verifies the large font preset applies 22px to the EPUB document. |
| P2 | Font, page width, page animation, flow, comic fit/quality/direction, PDF fit, and zoom used inconsistent densities. | Standardized them on compact segmented rows and a compact stepper, with format-appropriate options retained. | Chromium, standard WebKit, and iPhone WebKit exercise EPUB, comic, and PDF-adjacent setting paths without overflow or interception. |

### Fidelity surfaces

- Fonts and typography: retained the product's system/PingFang stack, reduced setting labels to the existing 12px control scale, and kept clear title/body hierarchy without truncating the long “微软雅黑” option at 390px.
- Spacing and layout rhythm: settings rows use a consistent 12px vertical rhythm, 4px segmented-control inset, and 6px dock selection inset; both 390px and 834px views remain uncropped.
- Colors and visual tokens: the four circles use the reader's actual day, warm, night, and black surface tokens; warm amber remains the selected/focus accent.
- Image quality and asset fidelity: no new raster assets were required; all controls use the installed Lucide icon set, including distinct Rows2/Rows3/Rows4 line-spacing icons.
- Copy and content: visible labels are shortened (`恢复默认`, `翻页`, `宽度`, `整页`) while exact accessible names remain available for theme choices, grouped presets, reset, and dock actions.
- Interaction/accessibility: selected options expose `aria-pressed`; panel triggers expose `aria-expanded`; selecting another dock action or tapping outside dismisses the active panel; focus trap, Escape dismissal, focus restoration, and 44px theme touch targets remain intact.

### Refinement verification

- TypeScript and ESLint: passed with no warnings.
- Unit tests: 94 passed.
- Chromium full reader E2E: 14 passed.
- Standard WebKit focused responsive/settings E2E: 5 passed.
- iPhone WebKit focused responsive/settings E2E: 5 passed.
- Visual comparison inspected at native scale; no page console errors or unresolved P0/P1/P2 findings remain.

## Top navigation, bounded TOC, and bookmark library — 2026-07-19

### Evidence

- User specification: remove the top-center content, connect the return and quick-bookmark actions in one long bar, constrain long TOCs to roughly half the screen with scrolling, and turn the bottom bookmark action into a saved-bookmark browser with jumping.
- The supplied clipboard screenshot was unavailable, so the current reader implementation plus the explicit interaction specification were used as source truth.
- Mobile EPUB with an 80-item scrollable TOC, 390×844: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-mobile-half-height-toc.png`.
- Mobile EPUB with two saved bookmarks, 390×844: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-mobile-bookmark-list.png`.

### Findings and resolutions

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 | The previous top controller split return, metadata, and bookmark into three floating objects even when the metadata was not needed. | Removed title/progress copy and placed the two retained 40px actions at opposite ends of one full-width rounded navigation bar. |
| P1 | A large TOC could consume most of the reading viewport. | Added a 55dvh maximum for TOC/list panels at mobile and desktop breakpoints; existing flex/overflow behavior now scrolls the entries inside that boundary. |
| P1 | The bottom bookmark action only toggled the current location, so saved locations were not discoverable or reusable. | Converted it to a selected/expanded bookmark panel with add/remove-current, ordered saved entries, current-location indication, individual deletion, and exact location jumping. |
| P2 | Comic bookmark storage was scoped per volume, preventing one list from representing the whole book. | Introduced book-wide v2 bookmark storage, merged legacy per-volume entries without deleting them, labeled comic bookmarks with volume titles, and added cross-volume page targets. |

### Fidelity and interaction checks

- Typography/copy: the top bar intentionally contains no title or progress text; bookmark entries use concise location, percentage, date, and current-state labels.
- Spacing/layout: the navigation bar spans the available top width with symmetric 4px inner padding; the 390×844 TOC is capped at 55% of the viewport and visibly scrolls.
- Colors/tokens: warm, night, and black surfaces retain existing border, shadow, amber-selected, and hover tokens.
- Icons/assets: existing Lucide back, bookmark, and delete icons are retained; no new production imagery was introduced.
- Accessibility: the top bar contains exactly two named buttons; bookmark and TOC triggers expose expanded state; rows have explicit jump/delete names; dialogs retain focus trapping, Escape dismissal, and outside dismissal.
- Capability coverage: EPUB bookmark add/list/jump/delete, large-TOC scrolling, comic cross-volume targets, legacy bookmark migration, and shared PDF location-command support were checked.

### Verification

- TypeScript and ESLint: passed with no warnings.
- Unit tests: 95 passed.
- Chromium full reader E2E: 15 passed.
- Standard WebKit focused responsive/bookmark E2E: 6 passed.
- iPhone WebKit focused responsive/bookmark E2E: 6 passed.
- No unresolved P0, P1, or P2 findings remain.

## Installed-PWA panel safe-area correction — 2026-07-19

- Reported surface: mobile installed mode; directory, bookmarks, annotations, and settings panels all showed excess space above their title/content.
- Root cause: bottom sheets added `--shuku-safe-area-top` to their own 16px top padding even though they are bottom-anchored and never enter the status-bar area.
- Fix: bottom-sheet top padding is now a stable 16px; the top navigation continues to consume the top safe area, and panel/dock bottom padding continues to protect the Home Indicator.
- Evidence: `/mnt/c/Users/gamer/.codex/visualizations/2026/07/19/019f7821-a97a-73f2-abc4-9ea71acf2451/reader-pwa-panel-safe-area-fixed.png` at 390×844 with simulated 47px top and 34px bottom safe areas.
- Coverage: Playwright switches directly among settings, directory, bookmarks, and annotations and verifies every panel computes 16px top padding. Chromium and iPhone WebKit checks passed; TypeScript and ESLint passed with no warnings.
- No unresolved P0, P1, or P2 findings remain.

final result: passed

---

# 列表批量选择与右键管理 QA — 2026-07-22

## 对照目标与证据

- 来源视觉：`/var/folders/d8/2c367y3s79b_hrmg8d1b8vzm0000gn/T/codex-clipboard-483b5f7b-da2f-4dea-9dcb-736ce1618834.png`，2978 × 1748 像素；来源用红框标出需要删除的工具栏“全选”入口，并保留当前筛选器与列表作为布局基准。
- 实现全视图：`docs/design/library-management-p0-p1/qa/batch-actions/library-filter-open-desktop.png`，1920 × 937 像素；CSS 桌面视口按 1920 × 937、1× 截图密度检查，状态为列表视图、更多筛选展开、1 条未填充书名规则、无选择项。
- 密度归一化：来源视觉按实现宽度等比缩放到 1920 × 1127；实现保持原始 1920 × 937，不额外放大。
- 同屏比较：`docs/design/library-management-p0-p1/qa/batch-actions/reference-implementation-comparison.png`，1920 × 2088 像素，上方为归一化来源，下方为浏览器实现。
- 重点交互证据：`docs/design/library-management-p0-p1/qa/batch-actions/right-click-menu-desktop.png` 与 `docs/design/library-management-p0-p1/qa/batch-actions/find-replace-dialog-desktop.png`，均为 1920 × 937 像素。右键菜单和查找替换内容在全尺寸截图中可直接读清，因此不再制作放大裁切。
- 来源截图不含当前应用左侧主导航，实现保留最新项目壳、设置入口和 1280px 内容区域，这是服从当前项目实际操作逻辑的有意差异。

## Findings 与比较迭代

- [P1 已修复] 工具栏仍显示独立“全选/取消全选”按钮，与用户指定的精简入口冲突。已删除该按钮；表头复选框继续作为熟悉且可访问的当前页全选方式。
- [P1 已修复] 列表只支持逐个勾选，无法覆盖连续选择和右键批处理意图。桌面行现在支持按下后拖动经过多行连续加入或移除、普通行点击切换、Shift 区间选择、表头全选以及复选框选择；右键未选中行会先把该行设为唯一选择，再打开批量菜单。
- [P1 已修复] 原批量弹窗仅有标签、状态、加入书架和系列名称等少量操作。右键菜单及底部批量入口现在统一提供元数据、查找替换、加入/移除书架、阅读状态和封面五类完整流程。
- [P1 已修复] 查找替换若直接执行会有大范围误改风险。已增加字段白名单、普通/正则匹配、大小写开关、最多 30 条预览、确认后执行，以及 `match/value/number/letter_upper/index` 安全 Jinja 变量；服务端不执行任意模板表达式。
- [P2 已修复] 第一次书架面板验收时，加载 effect 把自身 loading 状态作为依赖，重渲染后提前取消请求，导致“正在读取书架”停留。已移除自取消依赖，复测后会正确显示普通书架或“暂无普通书架”说明。
- [P2 已修复] 右键菜单若直接使用点击坐标，在屏幕右侧或底部会被裁切。菜单现在按 316 × 392 的实际占位在四边保留 12px 安全距离，并在滚动、缩放、外部点击或 Escape 时关闭。
- 最终没有未解决的 P0、P1 或 P2 视觉与交互问题。

## 五项视觉核对

- 字体与排版：沿用二毛图书当前中文系统字体栈；菜单采用 14px 主操作与 11px 说明，弹窗以 20px 标题、14px 表单和 12px 辅助信息形成清楚层级。安全模板使用等宽字呈现，长书名和元数据预览有截断或换行保护。
- 间距与布局：工具栏删除全选后没有留下空洞；右键菜单、底部选择条和最大 4xl 的批量弹窗使用现有 12/16/24px 节奏、暖白表面与一致圆角。弹窗正文独立滚动，标题和操作区保持可见。
- 颜色与令牌：继续使用暖白、暖灰、深棕和珊瑚强调色；选中行通过浅珊瑚底和 3px 内侧标记显示，不依赖系统蓝色选中态。
- 图片与图标：沿用真实图书封面和现有 Lucide 图标库；封面流程没有添加占位图、手绘 SVG 或 CSS 伪造资产。
- 文案与内容：五类菜单名与用户要求一一对应；未读明确说明清空阅读位置和进度，已读明确说明所有版本变为 100%，封面四种处理方式和替换文件约束均在执行前可见。

## 功能、响应式与数据验证

- Chrome 实测右键未选择行后只选中目标书；菜单展示五类操作；普通点击加 Shift 点击从第 1 行到第 3 行后正确选中 3 本。浏览器控制接口不暴露坐标级拖拽模拟，拖动逻辑由同一行事件状态机实现，并补充了失焦、鼠标释放和文本选择恢复边界。
- 实测在五类弹窗之间切换、关闭、Escape/外部点击、底部批量入口、空书架状态、元数据可选字段、阅读状态说明和封面条件表单；没有对现有三本图书提交写操作。
- 服务端隔离数据库实测：作者/出版社/系列/标签批量更新，书架加入和移除，安全模板预览与递增数字应用，未读清空全部进度，已读写入 100%，封面 2:3 裁剪、压缩、替换和重新生成全部通过。
- 移动端继续使用图书卡片复选框和底部“批量操作”入口；右键与鼠标拖选只在桌面列表出现。弹窗在 `md` 以下切换为底部面板，操作标签横向滚动，表单由多列降为单列。
- 浏览器首次热更新后出现一条既有 Reader V2 IndexedDB 关闭时序错误；刷新后消失，最终页面没有业务运行错误。当前 8000 端口是修改前启动且无热重载的 API 进程，浏览器内只验收了只读界面；新接口的真实写入与预览使用最新代码的隔离 API 测试完成。

## 自动化验证

- 后端完整测试：`287 passed, 5 skipped`。
- 新增批量能力定向测试：`4 passed`。
- 前端单元测试：`163 passed`。
- TypeScript：通过。
- ESLint：无 warning 或 error。
- `git diff --check`：通过。

final result: passed

---

# 图书馆管理 P0 + P1 元数据与分类治理实现 QA — 2026-07-22

## 对照目标

- 交互与视觉来源：`prototypes/library-management-p0-p1/`。
- 实现基准：当前书库、作品详情、书架以及 2026-07-22 更新后的设置中心；智能整理能力落在 `/settings/organize`，没有恢复旧版独立设置壳。
- 桌面实现截图：`docs/design/library-management-p0-p1/qa/implementation-library-desktop.png`、`docs/design/library-management-p0-p1/qa/implementation-settings-duplicates-desktop.png`。
- 移动实现截图：`docs/design/library-management-p0-p1/qa/implementation-library-mobile.png`、`docs/design/library-management-p0-p1/qa/implementation-settings-duplicates-mobile.png`。
- 同屏对照：`docs/design/library-management-p0-p1/qa/comparison-library-mobile.png`、`docs/design/library-management-p0-p1/qa/comparison-organize-mobile.png`。

## 数据与交互验收

- 批量管理：实测选择 2 本作品并批量添加标签；后端同时支持移除标签、设置阅读状态、加入普通书架和设置丛书名称。
- 智能书架：实测将当前检索与类型、状态、标签条件保存为智能书架；书架按规则动态计算成员，不允许手工增删动态成员。
- 重复作品：实测识别同标题/作者候选、指定主作品、合并版本/进度/书架关系，并通过操作记录撤销恢复；源文件不删除。
- 分类治理：实测作者、标签、丛书、出版社四类规范化实体的检索、重命名和多选合并；旧名称作为别名保留，操作可撤销。
- 元数据模型：作品级与版本级字段分层；实测编辑版本名称与出版社，详情页立即刷新。
- 版本拆分：实测将 PDF 版本从多版本作品拆分为独立作品，源作品版本数同步更新，并保留可撤销操作记录。
- 数据库迁移：Schema 升级到 v9；既有作品/版本字段会回填到规范化分类表，兼容部分旧测试库与旧字段。

## 响应式与视觉结论

- 桌面书库延续现有主导航与卡片体系；新增批量管理、保存筛选和更多筛选入口，没有引入第二套管理控制台。
- 桌面设置页使用最新设置主侧栏；智能整理正文包含整理队列、重复项、分类治理、识别设置和数据源配置五个分区。
- 移动端继续使用当前汉堡菜单与设置分类网格；能力入口和原型语义一致，但主动服从最新设置界面结构。
- 修正 360px 书库标题截断；书库与智能整理页面均无横向溢出。
- 浏览器未出现业务错误；仅记录 Next.js 对测试封面首屏图片的 LCP `priority` 开发提示，不影响功能或布局。
- 没有未解决的 P0、P1 或 P2 交互问题。

## 自动化验证

- 后端完整测试：`293 passed, 5 skipped`。
- 前端单元测试：`163 passed`。
- TypeScript：`tsc --noEmit` 通过。
- ESLint：无 warning 或 error。
- Next.js production build：通过。
- `git diff --check`：通过。

final result: passed

---

# 智能筛选器下拉样式回归 QA — 2026-07-22

## 对照目标与证据

- 缺陷来源截图：`/var/folders/d8/2c367y3s79b_hrmg8d1b8vzm0000gn/T/codex-clipboard-7f63e1ea-3b81-442d-b37a-afe81042a0d2.png`，2034 × 1008 像素。
- 修复后桌面截图：`docs/design/library-management-p0-p1/qa/smart-filter-styled-dropdown-desktop.png`，2034 × 1008 像素。
- 修复后移动截图：`docs/design/library-management-p0-p1/qa/smart-filter-styled-dropdown-mobile.png`，375 × 812 像素；CSS 外部视口 390 × 844，内容宽度 375，1× 密度。
- 同状态全视图比较：`docs/design/library-management-p0-p1/qa/smart-filter-styled-dropdown-comparison.png`，上下拼接同尺寸桌面截图；状态均为“文件格式 / 等于 / EPUB”，字段菜单展开。
- 桌面对照采用 CSS 视口 2034 × 1008、1× 密度；来源和实现像素尺寸一致，不需要缩放归一化。
- 未单独制作聚焦裁切：菜单本身占据来源截图的主要高对比区域，同尺寸全视图比较中字段、分组、选中态、滚动条和弹层边界均可直接读清。

## Findings 与比较迭代

- [P1 已修复] 字段选择使用浏览器原生 `select`，展开后出现深灰系统菜单、蓝色系统选中态，遮挡大面积页面且与二毛图书视觉语言完全脱节。已统一替换为项目自有的浅色选择器：暖灰边框、珊瑚选中态、分组标题、圆角、阴影和 288px 有界滚动区。
- [P2 已修复] 可自定义的作者、标签、出版社、格式等值编辑器仍依赖原生 `datalist`，会在不同浏览器中继续出现未应用样式的候选菜单。已替换为可输入、可筛选、可键盘选择的自有组合框。
- [P2 已修复] 普通绝对定位菜单会被筛选卡片的裁切边界截断，并可能在小屏超出视口。菜单现在通过页面级弹层渲染，根据上下剩余空间定位，并在水平两侧保留 12px 安全距离。
- 修复后桌面菜单矩形为 280 × 288，位于视口 `left 585 / right 865 / top 353 / bottom 641`，无横向溢出；移动菜单为 280 × 288，位于 `left 50 / right 330 / top 452 / bottom 740`，同样无横向溢出。
- 最终没有未解决的 P0、P1 或 P2。浏览器控制台没有筛选器相关 error/warn；仅保留两条既有封面图 LCP 开发提示，不属于本次交互缺陷。

## 五项视觉核对

- 字体与排版：菜单继承现有中文字体栈；分组为 11px 次级标题，选项为 14px，层级和行高稳定。
- 间距与布局：触发器继续对齐条件行网格；菜单宽 280px、最大高 288px，桌面和移动端均未遮住永久操作入口，也没有页面横向滚动。
- 颜色与令牌：使用现有白色面板、暖灰边框、暖灰正文、珊瑚悬停和选中态，没有系统深色菜单或蓝色系统高亮残留。
- 图片与图标：只使用项目现有 Lucide 勾选和箭头图标；没有新增替代图像、占位符或手绘资产。
- 文案与内容：五个筛选分组及 36 个字段保持完整；候选值继续显示数据库计数，自定义值空结果提供明确提示。

## 交互与自动化验证

- 实测字段菜单长列表滚动并选择“文件格式”；实测可输入候选值菜单选择 `EPUB` 后结果由 3 本实时收敛为 2 本。
- 实测字段菜单通过方向键从“文件格式”移动到“文件总大小”并回车确认；Escape、菜单外点击和选项点击均能正确收起。
- 智能筛选区域内原生 `select` 数量为 0；字段、运算符、组合方式、固定候选值和可自定义候选值均使用应用自有样式。
- TypeScript：通过。
- ESLint：无 warning 或 error。
- 前端单元测试：`163 passed`。
- `git diff --check`：通过。

final result: passed

# 元数据源组合与配置列表设计 QA — 2026-07-21

## 验收范围

- 数据源识别链路拆分为电子书、漫画、有声书三个独立区域。
- 每个区域可以独立添加、移除、启停数据源，并调整识别优先顺序。
- 数据源自身的连接状态、测试与参数配置收拢到独立“数据源配置”列表。

## 视觉证据

- 参考图：`/var/folders/d8/2c367y3s79b_hrmg8d1b8vzm0000gn/T/codex-clipboard-9587a715-3682-4b14-a65d-36ec5c9cb7bc.png`。
- 最终实现：`docs/design/metadata-organization-refactor/qa/implementation-provider-pipelines-v3.png`。
- 同屏对照：`docs/design/metadata-organization-refactor/qa/comparison-provider-pipelines-v3.jpg`，左侧为参考图，右侧为最终生产实现。

## 交互与功能核对

- 电子书、漫画、有声书分别展示自己的有序数据源组合；默认组合与插件声明的支持类型一致。
- 上移、下移、添加、移除和启用开关均按读物类型独立保存，不会连带修改其他区域。
- 手动元数据搜索与后台识别任务共同读取同一套类型化数据源配置，禁用的数据源不会被绕过调用。
- 数据源配置以独立列表呈现；配置操作使用居中弹窗，测试入口和连接状态保留。
- 实测切换豆瓣数据源后状态可持久化，并已恢复测试前状态；AI 配置弹窗可正常打开和关闭。
- 2048 × 1200 桌面视口无横向溢出：`innerWidth 2048`、`scrollWidth 2033`、`scrollHeight 1204`。

## 自动化验证

- 后端完整测试：`289 passed, 5 skipped`。
- 前端完整测试：`175 passed`。
- TypeScript `tsc --noEmit` 通过。
- Next.js production build 通过。
- `git diff --check` 通过。

final result: passed

---

# 整理识别策略与插件配置 QA — 2026-07-21

## 对照证据

- 识别设置来源：`/var/folders/d8/2c367y3s79b_hrmg8d1b8vzm0000gn/T/codex-clipboard-87a659ef-3b29-44ae-84fc-7139c1e05661.png`。
- 插件列表来源：`/var/folders/d8/2c367y3s79b_hrmg8d1b8vzm0000gn/T/codex-clipboard-b1527124-bf56-4348-89c3-2db6af43b987.png`。
- 识别设置实现：`docs/design/metadata-organization-refactor/qa/implementation-recognition-overwrite-v2.png`。
- 插件弹窗实现：`docs/design/metadata-organization-refactor/qa/implementation-provider-config-modal-v2.png`。
- 系统状态下拉实现：`docs/design/metadata-organization-refactor/qa/implementation-queue-system-select-v2.png`。
- 同屏比较：`docs/design/metadata-organization-refactor/qa/comparison-recognition-overwrite-v2.png`、`docs/design/metadata-organization-refactor/qa/comparison-provider-modal-v2.png`。
- 视口：识别页和交互检查使用桌面 `1962 × 1478`；状态为新安装、无书籍、默认策略。

## 视觉与交互核对

- 字体与排版：沿用现有设置中心字号、字重和中文字体回退；新标题及说明保持原设置行层级。
- 间距与布局：第三个策略行仍使用既有分隔和留白；删除质量阈值后，识别范围稳定为两列；插件配置由右侧抽屉改为居中 640px 模态窗。
- 颜色与令牌：开关、焦点环、按钮和选中态继续使用现有珊瑚色语义令牌，无新增颜色体系。
- 图片与图标：未替换产品图片；继续使用项目已有 Lucide 图标与插件图标组件，无占位或 CSS 绘图。
- 文案：页面显示“覆盖已有标题和作者”，说明其他元数据只补缺失字段；不再出现质量阈值文案。
- 主要交互：默认覆盖开关为开启；插件弹窗支持遮罩点击、关闭按钮和 Escape；整理状态使用系统 `Select`，五个选项均可见且 DOM 中不存在对应原生 `select`。
- 控制台：识别页、插件弹窗及状态下拉打开态均无 error/warn。

## 比较迭代

| 级别 | 早期发现 | 修正 | 修正后证据 |
| --- | --- | --- | --- |
| P2 | 系统状态下拉放入原队列卡片后，被父级 `overflow-hidden` 裁掉“识别中”和“等待中”。 | 移除队列卡片的裁切，让系统组件菜单在边框外正常展开。 | `implementation-queue-system-select-v2.png` 中五项完整显示；各选项可见区域均为 118 × 36px。 |

没有未解决的 P0、P1 或 P2。识别设置与来源截图的整体信息层级、圆角、分隔线和控件密度一致；插件弹窗是本轮明确要求的交互变更，因此有意覆盖来源截图中未打开配置时的状态。

final result: passed

# 整理队列自动化收口 QA — 2026-07-21

## 交互收口

- 整理队列行级操作收敛为“重新识别 / 删除”，桌面表格和移动卡片保持一致。
- 删除前明确提示“不会删除书库读物或文件”；重新识别从任意状态可用，并按当前启用的数据源重新生成执行计划。
- 整理详情删除“元数据建议”和“重复/版本候选”，只保留当前元数据完整度、任务摘要和读物跳转。
- 导入记录不再展示“重复”标记，汇总改为“已完成 / 失败”；文件内容去重仍作为底层安全机制保留。

## 数据与状态核对

- 整理列表和详情 API 不再返回 `suggestions` / `duplicates`，旧的建议应用、候选合并和刷新端点均不再对外暴露。
- “自动补全空字段”开启时仅写入空字段；关闭时仅保存识别原始结果，不修改作品元数据。
- 无唯一候选、无可用数据源或重试耗尽均统一落入队列“失败”状态，不再进入人工建议审核。
- 删除整理记录同步删除查询任务和插件执行记录，不删除 `LibraryWork` 及其文件。

## 最终验证

- 后端完整测试：`288 passed, 5 skipped`。
- 前端完整单元测试：`175 passed`。
- TypeScript：`tsc --noEmit` 通过。
- Next.js production build：通过。
- `git diff --check` 通过。

final result: passed

---

# 整理记录列表收敛设计 QA — 2026-07-21

## 验收范围

- “整理队列”改为完整整理记录视图，统一展示成功、失败、识别中、等待中四类状态；隐藏作品和已完成任务也保留在历史中。
- 列表补齐入队原因、状态、数据源、入队时间，搜索框和状态筛选并入列表表头。
- 删除添加标签、应用建议、应用建议并完成、隐藏、确认整理、从书库加入、立即扫描及其前台请求链路；详情页同步收敛为只读历史。
- 任务只由定时策略或新增后自动执行产生；识别设置只保存策略，不隐式触发扫描。

## 视觉真值与同屏证据

- 视觉基准：`docs/design/metadata-organization-refactor/direction-a-queue-hub.png`。
- 最终桌面实现：`docs/design/metadata-organization-refactor/qa/implementation-history-v2.png`。
- 整页同屏对照：`docs/design/metadata-organization-refactor/qa/history-reference-vs-implementation-v3.jpg`。
- 表格重点对照：`docs/design/metadata-organization-refactor/qa/history-table-focused-comparison-v2.jpg`。
- 移动端卡片：`docs/design/metadata-organization-refactor/qa/implementation-history-mobile-cards-v2.png`。
- 桌面视口为 1640 × 959；移动端按 390 × 844 视口验收，页面无水平溢出。

## 发现与修正

| 级别 | 发现 | 处理结果 |
| --- | --- | --- |
| P1 | 原列表只返回活动任务，成功记录、隐藏作品和已处理任务会消失。 | API 改为返回完整历史，并将底层任务/识别状态归一为四类用户状态。 |
| P1 | 原主列表同时承担选择、批量应用和确认，和“完整整理记录”的只读语义冲突。 | 删除复选框、批量操作、候选修改和确认按钮；行级仅保留“详情”。 |
| P1 | 删除按钮后仍存在手动创建 Run/Job 的公开接口会形成旁路。 | 移除前端调用及公开 `POST /api/organize/runs`、`POST /api/organize/jobs` 端点，scheduler 内部编排保持不变。 |
| P2 | 搜索和状态筛选位于列表之外，用户难以理解作用范围。 | 两个控件合并到同一列表表头，并显示当前结果数/总数。 |
| P2 | 桌面六列在手机上无法稳定阅读。 | 小屏切换为包含同等字段的只读卡片；状态置于首行，原因、数据源和时间分组展示。 |

设计稿中的“从书库加入”“立即扫描”、选择框和批量按钮是本轮明确删除的交互，因此最终实现有意偏离这些控件；暖白背景、珊瑚强调、轻分隔线、圆角列表、信息密度和侧栏体系继续以设计稿为准。字体、间距、颜色、图片质量和中文文案均已逐项核对。

## 交互验证

- 四种状态各使用一条真实结构的 QA 数据进行验收；状态筛选“失败”只显示 1 / 4 条记录。
- 搜索“Bangumi”只显示匹配该数据源的 1 / 4 条记录，书名、作者、入队原因和数据源均在搜索范围内。
- 详情入口可打开对应历史记录，页面不出现应用、确认、隐藏或手动识别动作。
- 移动端四条记录均转换为卡片，字段完整且无水平滚动；浏览器控制台无错误。

## 最终验证

- 后端完整测试：`286 passed, 5 skipped`。
- 前端完整单元测试：`175 passed`。
- TypeScript：`tsc --noEmit` 通过。
- Next.js production build：通过，31 个页面完成生成。
- 无未解决 P0、P1 或 P2 问题。

final result: passed

---

# 元数据整理能力重构设计 QA — 2026-07-21

> 阶段性历史记录：本节保留第一轮“活动队列 + 手动加入/扫描”实现证据；队列形态已由上方“整理记录列表收敛设计 QA”取代。

## 验收范围

- 上传、手动导入和监控目录只负责作品入库，不再直接创建整理任务；新作品保持 `UNASSESSED`。
- 整理编排器统一处理手动加入、立即扫描、定时间隔和“新增后自动执行”，并负责去重、运行批次和队列状态。
- 豆瓣、Bangumi、AI 通过同一插件注册表提供能力，可独立启停、排序、配置和连接测试，并支持 Python entry point 扩展。
- 设置页采用已确认的“队列中枢 + 独立识别设置 + 数据源插件”结构；队列页提供右侧识别设置抽屉。

## 同屏视觉证据

- 最终设计参考：`docs/design/metadata-organization-refactor/final-queue-with-settings-sheet.png`。
- 参考与实现同屏对照：`docs/design/metadata-organization-refactor/qa/queue-reference-vs-implementation-v1.jpg`。
- 桌面队列：`docs/design/metadata-organization-refactor/qa/implementation-queue-v1.png`。
- 队列识别设置抽屉：`docs/design/metadata-organization-refactor/qa/implementation-queue-settings-sheet-v1.png`。
- 识别设置页：`docs/design/metadata-organization-refactor/qa/implementation-recognition-v2.png`。
- 数据源插件页：`docs/design/metadata-organization-refactor/qa/implementation-providers-v1.png`。
- 移动端队列：`docs/design/metadata-organization-refactor/qa/implementation-queue-mobile-full-v1.png`。

## 视觉核对与修正

| 级别 | 发现 | 处理结果 |
| --- | --- | --- |
| P1 | 原导入链路直接写整理队列，无法区分“已入库”和“已安排整理”。 | 移除 Importer 的任务创建调用；新增候选集和 Organizer 主动建 Run/Job 的边界。 |
| P1 | 元数据来源在后端、任务队列和识别弹窗中多处硬编码。 | 增加统一 ProviderRegistry、manifest、动态 API 和前端动态来源列表；内置来源也走插件协议。 |
| P2 | 运行状态、策略入口和候选作品分散，用户不清楚谁会进入队列。 | 队列顶部增加运行状态带、候选数量、“从书库加入”“立即扫描”和识别设置抽屉。 |
| P2 | 设置较多时会挤压队列扫描效率。 | 高频队列和低频配置拆成页签，桌面抽屉只承载快速调整；移动端使用单列卡片。 |
| P2 | 所有数据源被关闭时，作品识别弹窗仍可能提交无效请求。 | 动态判断当前来源是否启用且适用；没有可用来源时禁用搜索/识别按钮。 |

## 交互与功能核对

- 实测“立即扫描”将 4 本候选作品一次性加入队列，并显示活动任务状态。
- 实测打开右侧识别设置抽屉、切换“新增后自动执行”并保存，刷新后配置保持。
- 实测豆瓣插件启停、AI 配置保存和连接测试入口；插件卡片、适用类型和健康状态均可见。
- 桌面和移动端均可访问队列、候选加入、搜索/状态筛选、识别设置和数据源插件。

## 最终验证

- 后端完整测试：`285 passed, 5 skipped`。
- 前端完整单元测试：`175 passed`。
- TypeScript：`tsc --noEmit` 通过。
- Next.js production build：通过，静态页面与动态路由生成完成。
- `git diff --check` 通过；无未解决 P0、P1 或 P2 问题。

final result: passed

# 整理队列状态带删除设计 QA — 2026-07-21

- Source visual truth：`/var/folders/d8/2c367y3s79b_hrmg8d1b8vzm0000gn/T/codex-clipboard-1caad395-251e-417d-b278-2790e47ce898.png`，红框标注整条待删除区域。
- Implementation screenshot：`docs/design/metadata-organization-refactor/qa/implementation-history-no-status-band-v3.png`。
- Full-view comparison：`docs/design/metadata-organization-refactor/qa/history-remove-status-band-comparison-v3.jpg`。
- Viewport/state：Chrome 1920 × 993，`/settings/organize?tab=queue`，2 条真实整理记录。
- Focused comparison：本次唯一变化是整块区域删除，红框在全视图中边界与内容均清晰可辨，无需额外局部裁切。
- Finding/fix：原“整理记录已同步 / 调整识别设置”状态带占用一整行；已删除状态带、设置抽屉触发器及其不可达状态，列表说明后直接进入筛选表头。
- Typography：未改动现有字号、字重和层级；删除后说明与表格层级连续。
- Spacing/layout：表格上移，保留原页面节奏且没有残留空容器或异常留白。
- Colors/tokens：未新增或修改颜色；原暖白、珊瑚强调和表格语义色保持不变。
- Image quality：书封与图标均使用原资产，截图无拉伸、模糊或替代资产。
- Copy/content：被标注行的两段文案及“调整识别设置”按钮均已消失；页签中的“识别设置”入口仍保留。
- Interaction/console：搜索、状态筛选、刷新和详情入口仍存在；控制台无错误；DOM 中被删除文案及按钮数量均为 0。
- Comparison history：首次实现即完整删除标注区域，未发现需要继续修复的 P0/P1/P2 差异。

final result: passed

---

# 有声书与多媒介详情设计 QA

> 阶段性历史记录：本节保留最初“完整播放器 + 迷你播放器”实现的验收证据；播放器形态已由文末“迷你播放器收敛”验收结论取代。

## 验收对象

- 确认方向：`docs/design/audiobook/refined-concept-01-underline-tabs.png`
- 生产实现：`http://127.0.0.1:3000/works/py_1784517013525761000`
- 测试作品：同一个 Work 下包含 EPUB、CBZ 与双轨 MP3 有声书。
- 对照视口：设计源图与实现均为 `1487 × 1058`。

## 视觉证据

- 详情页实现：`docs/design/audiobook/qa/implementation-audiobook-detail.png`
- 完整播放器：`docs/design/audiobook/qa/implementation-audio-player.png`
- 同屏对照：`docs/design/audiobook/qa/comparison-option-01-vs-implementation.png`，左侧为确认稿，右侧为最终生产实现。

## 视觉核对

- 使用确认的一号方向：纯文字“电子书 / 漫画 / 有声书 / 内容结构”标签与珊瑚橙下划线，不使用分段胶囊控件。
- 保留现有产品的暖象牙白、细边框、低阴影、珊瑚橙主操作与侧栏体系。
- 作品标题、作者、简介和封面在媒介切换时保持稳定；格式、版本、演播、进度、当前位置、状态、CTA 与目录同步切换。
- 有声书详情保持阅读详情页层级，完整播放舞台单独进入 `/listen/{editionId}`。
- “内容结构”选中时不显示消费进度、消费状态和阅读/播放 CTA，只展示跨媒介版本结构。
- 真实测试数据只有两章，因此章节密度与设计稿示例不同；组件结构、选中态、时间信息和交互层级一致。

## 功能核对

- 缺失媒介标签自动隐藏；后端顺序生效；最后标签按用户与 Work 持久化。
- 标签支持鼠标与键盘方向键切换，选中标签与 tabpanel 语义关联正确。
- 从详情页章节或“继续听”进入完整播放器；播放、暂停、15 秒后退、30 秒前进、切章、跨轨、倍速、音量与睡眠定时可用。
- 全局迷你播放器跨详情与播放器路由保持状态，可继续、暂停、切章、打开完整播放器或关闭。
- 真实 MP3 从第一轨连续播放到第二轨，并由原生 `ended` 提交完成；普通 seek 到末尾不会误判完成。
- 进度回到详情页后实时投影，并在关闭播放器、刷新页面后恢复到相同章节和位置。
- 手动将完成状态改回“在听”后可持久化，不会因页面刷新回退。
- Reader V2 音频 bootstrap 返回稳定轨道、章节、时长、MIME 与 `AudioProgressLocation`。
- 真实文件请求验证：HEAD `200`；`bytes=0-31` 与后缀 Range 均为 `206`；越界 Range 为 `416`；响应包含 `Accept-Ranges`、`ETag`、`Content-Length` 与正确 `Content-Range`。
- 内容结构键盘切换实测通过；页面控制台无错误。

## 自动化证据

- 后端：`267 passed, 5 skipped`；有声书专项 `15 passed`。
- 前端：`170 passed`。
- TypeScript `tsc --noEmit` 通过。
- Next.js production build 通过。
- OpenAPI 导出与 Reader V2 TypeScript 客户端重新生成后无漂移。
- `git diff --check` 通过。

## 迭代记录

1. 将早期分段式版本控件收敛为确认稿的纯文字下划线标签。
2. 媒介切换时固定 Work 级封面与书目信息，仅切换消费上下文。
3. 补齐有声书 CTA 的用户手势内自动播放、跨路由迷你播放器与实时详情投影。
4. 将 API 返回的标签与真实可用媒介求交集，避免删除或隐藏媒介后出现幽灵标签。
5. 增加标签 roving focus、方向键/Home/End 操作与正确 ARIA 关系。
6. 使用真实三媒介 Work、真实 MP3、最终生产构建进行同视口视觉与播放验收。

final result: passed

---

# 有声书迷你播放器收敛设计 QA — 2026-07-20

## 验收范围

- 产品内仅保留一个跨页面全局迷你播放器；原独立完整播放器不再作为产品界面存在。
- 原完整播放器的章节/音轨、上一章/下一章、后退 15 秒、前进 30 秒、整本进度、倍速、音量与睡眠定时全部集中到迷你播放器及其上浮面板。
- 图书详情、章节行、内容结构与首页“继续听”均在当前页面直接启动迷你播放器；播放器信息区进入带 `detailTab=AUDIOBOOK` 与 `editionId` 的图书详情。
- 旧 `/listen/{editionId}` 只保留历史链接兼容：定位章节或音轨后替换为规范图书详情 URL，不再渲染第二套播放器。

## 同屏视觉证据

- 来源与最终实现同屏对照：`docs/design/audiobook/qa/comparison-mini-player-consolidation.png`。
- 最终桌面常驻态：`docs/design/audiobook/qa/mini-player-after-desktop.png`。
- 最终桌面播放设置：`docs/design/audiobook/qa/mini-player-settings-desktop.png`。
- 最终桌面章节面板：`docs/design/audiobook/qa/mini-player-chapters-desktop.png`。
- 390 × 844 移动端：`docs/design/audiobook/qa/mini-player-mobile.png` 与 `docs/design/audiobook/qa/mini-player-settings-mobile.png`。
- 844 × 390 横屏矮视口：`docs/design/audiobook/qa/mini-player-settings-landscape.png`。

## 视觉核对与修正

| 级别 | 发现 | 处理结果 |
| --- | --- | --- |
| P1 | 完整播放器与迷你播放器形成两套入口、两套控制层级。 | 删除完整播放器实现；常驻条保留核心播放控制，章节与设置以互斥上浮面板承载完整能力。 |
| P1 | 首次 bootstrap 失败时旧迷你播放器没有可见状态，用户会认为点击无响应。 | 增加带书名、封面与目标章节的准备/失败外壳、重试及关闭操作。 |
| P1 | 失败重试可能丢失用户点选章节。 | 保留失败请求的 edition、chapter 与启动摘要；重试成功后仍进入原目标章节并立即播放。 |
| P1 | 详情深链参数可能压过用户后续标签或版本选择。 | 标签与版本切换同步更新 URL，并跳过同一次本地查询同步造成的重复重置；刷新保持最新选择。 |
| P2 | 切换新有声书失败后，已暂停保留的原播放会话没有恢复入口。 | 失败/加载外壳在存在旧会话时提供“返回原播放”，不清空原 bootstrap 和进度。 |
| P2 | 手机横屏矮视口的上浮面板可能超出屏幕顶部。 | `max-height: 520px` 的移动横屏改为安全区内固定可滚动面板，并提升层级覆盖迷你条；底部睡眠选项可滚动点击。 |

## 交互与无障碍核对

- 详情页与首页“继续听”、详情章节选择均保持当前 URL 并出现迷你播放器；章节选择立即播放。
- 点击迷你播放器的书目信息，从首页返回对应 Work 的有声书标签与版本；播放控制、滑杆、章节和设置不会触发导航。
- 标签/版本深链切换后刷新可恢复最新状态；播放器链接再次点击可重新定位到有声书标签。
- 旧 `/listen/{editionId}?chapter=...` 实测自动替换到图书详情、保留目标章节并保持暂停，等待用户手势播放。
- 倍速 `0.75×–3×`、音量、15/30/45/60 分钟、本章结束、关闭睡眠定时、整本进度、章节/音轨切换均可达。
- 面板支持 Escape、外部点击与明确关闭按钮；触发器提供 `aria-expanded` / `aria-controls`，移动控件最小触控尺寸为 44px。
- 加载新版本失败时“返回原播放”实测恢复旧章节；API 恢复后重试实测仍定位到失败前点选的章节。

## 最终验证

- 后端完整测试：`268 passed, 5 skipped`。
- 前端完整单元测试：`170 passed`。
- TypeScript：`tsc --noEmit` 通过。
- Next.js production build：通过，Lint/类型阶段无新增警告。
- 真实双轨 MP3：播放、跨轨、章节定位、失败重试、进度投影与持久化实测通过。
- 桌面 `1487 × 1058`、移动竖屏 `390 × 844`、移动横屏 `844 × 390` 视觉与控制可达性通过。
- `git diff --check` 通过；无未解决 P0、P1 或 P2 问题。

final result: passed

---

# 设置聚焦模式 QA — 2026-07-22

## 对照目标

- 来源视觉：`docs/design/management-console/ermao-console-selected-settings-shell.png`。
- 来源像素尺寸：1487 × 1058；桌面 Web 应用状态，无浏览器框架。
- 实现截图：`docs/design/management-console/qa/settings-shell-implementation.png`。
- 全屏同视口对照：`docs/design/management-console/qa/settings-shell-comparison.jpg`。
- 重点区域对照：`docs/design/management-console/qa/settings-shell-focused-comparison.jpg`。
- 移动端回归：`docs/design/management-console/qa/settings-shell-mobile.png`。
- 桌面实现视口与截图：1440 × 1024 CSS 像素，1× 密度，截图 1440 × 1024；来源图等比归一化到 1440 × 1024 后进行对照。
- 移动端实现视口与截图：390 × 844 CSS 像素，1× 密度，截图 390 × 844。
- 状态：本地 `/settings`，已登录，通用设置页；移动端同一路由。

## 同屏核对与结论

- 字体与排版：实现继续使用现有二毛图书字体栈、字号和字重；标题、说明、列表与表单层级和当前生产设置页一致。
- 间距与布局：桌面端将既有设置分类从内容区左栏迁移到应用主侧栏，设置正文扩展为单栏；来源稿的局部放大比例没有照搬，以保持当前设置内容的真实密度。1440px 下 `scrollWidth` 为 1425，没有横向溢出。
- 颜色与令牌：继续使用现有 `#FBFAF8`、`#F3F0EC`、`#FCFBF9`、`#FF4F2A` 与暖灰分隔令牌。
- 图片与图标：继续使用现有二毛猫图标与 Lucide 图标，没有新增替代资产。
- 文案与内容：七个设置分类、页面标题、说明、字段、按钮和业务组件均保持现状；没有加入概览、状态、成员或媒体库内容。
- 重点区域对照可直接检查品牌、返回入口、设置选中态、标题、排序列表和操作按钮，因此不再需要额外的小尺寸裁切。
- 没有未解决的 P0、P1 或 P2；来源稿与实现的密度差异是“完全移植现有设置内容”的有意约束。

## 交互与响应式验证

- 从首页点击桌面侧栏头像可进入 `/settings`，原书库导航完整替换为七个设置分类和“返回阅读”。
- 点击“数据与系统”进入 `/settings/data`，页面标题正确；点击“返回阅读”回到首页后，搜索、首页、书库和书架导航恢复，设置导航消失。
- 390 × 844 下桌面侧栏隐藏，原设置分类网格保持可见，通用设置内容不变，`scrollWidth` 为 375，没有横向溢出。
- 桌面与移动验收状态均无浏览器 error/warn。

## 自动化验证

- TypeScript：通过。
- 前端单元测试：163 passed。
- Next.js production build：通过。
- `git diff --check`：通过。

final result: passed

---

# 动态智能组合筛选 QA — 2026-07-22

## 对照目标与证据

- 来源视觉：`/var/folders/d8/2c367y3s79b_hrmg8d1b8vzm0000gn/T/codex-clipboard-1c6abb16-5691-4d17-beb0-ec33ef464a6c.png`，2872 × 844 像素。
- 来源密度归一化：按实现 CSS 视口宽度由 2872 × 844 归一化到 2048 × 602；来源截图不含现有应用侧栏，实现继续保留当前产品壳。
- 桌面实现：`docs/design/library-management-p0-p1/qa/smart-filter-desktop.png`，2048 × 900 像素，CSS 视口 2048 × 900，1× 密度。
- 移动实现：`docs/design/library-management-p0-p1/qa/smart-filter-mobile.png`，375 × 1642 像素；CSS 外部视口 390 × 844，内容宽度 375，1× 密度。
- 同屏对照：`docs/design/library-management-p0-p1/qa/smart-filter-comparison-desktop.png`；实现按来源归一化高度裁切到 2048 × 602 后纵向同屏比较。
- 重点区域已在同屏图中以可读尺寸呈现完整工具栏、筛选表头和条件行，不需要额外裁切。

## 五项视觉核对

- 字体与排版：沿用当前二毛图书字体栈与字重；标题、工具栏、字段、运算符和值的层级清楚，条件编号和辅助说明保持次级权重。
- 间距与布局：实现保留现有固定侧栏和 1280px 内容框架；筛选器贴在工具栏下方，条件行使用稳定的“字段—运算符—值—删除”列。移动端改为纵向字段堆叠。
- 颜色与令牌：继续使用现有暖白背景、暖灰边框、珊瑚色激活态和黑色主操作，没有引入第二套视觉系统。
- 图片与图标：沿用现有真实封面和项目图标库；没有新增占位图、手绘 SVG 或替代资产。
- 文案与内容：明确区分“全部条件/任一条件”、动态字段、条件运算和值；空条件不参与查询，未补全条件不可保存。

## 交互与数据验证

- 动态 schema 返回 36 个筛选维度，覆盖作品元数据、版本元数据、格式与文件、阅读与整理、来源与归档五组。
- 支持文本、枚举、数值、日期、布尔和区间运算；最多 30 条条件，顶层可选择全部匹配或任一匹配。
- 实测普通书架条件命中 2 本，再叠加出版社条件后命中 1 本；切换任一匹配并改为另一出版社后命中 3 本。
- 实测将 2 条任一匹配规则保存为智能书架，书架详情动态返回 3 本作品；规则和动态选项均来自真实数据库。
- 实测阅读状态筛选命中 2 本；桌面 1265px 和移动内容宽度 375px 均无横向溢出。
- 新建干净浏览器标签完成最终回归，console 无 error 或 warn。

## 比较迭代

- P2：筛选 schema 首次请求完成后界面仍停留在加载态。原因是 effect 将自身 loading 状态列入依赖并在重渲染时提前取消；已移除该依赖并实测动态字段可正常进入。
- P2：初版在没有基础条件时仍显示一整行重复说明，增加首屏高度。已改为仅在丛书或阅读状态入口条件存在时显示基础条件条；最终筛选器直接贴合工具栏。
- P2：开发期热更新改变 effect 依赖长度产生一次 React 开发警告。完整重启后使用新标签复测，最终 console 为空；生产构建同样通过。
- 最终没有未解决的 P0、P1 或 P2；保留当前应用侧栏和较紧凑内容宽度是遵循现有产品逻辑的有意差异。

## 自动化验证

- 后端完整测试：`294 passed, 5 skipped`。
- 前端单元测试：`163 passed`。
- TypeScript：通过。
- ESLint：无 warning 或 error。
- Next.js production build：通过。
- `git diff --check`：通过。

final result: passed
