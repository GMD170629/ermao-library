# 手机 Web 电子书阅读器修复记录

日期：2026-10-23。已修正 SDK 出版物声明、PWA 外层布局，以及设置面板对 Readium 宿主施加 inert 导致切换后原生滚动失效的问题；完整新构建的手机 PWA 模式切换后纵向滚动验收通过。未发布或修改 NAS 部署。

## 范围与归属

仅修改 Web Reader 现有外壳、Readium 展示映射、当前文档选择和本地 Publication 装配。保留工作区无关修改，不改变原文件、缓存、Reader v5 协议、后端或原生 App。

滚动和分页均使用 Readium 原生模块及公开偏好接口。没有修改 SDK 补丁、依赖版本或锁文件，没有新增滚动容器、手势翻页管线或时序去重。

## 滚动失效与误翻章

真实 iPhone PWA 失败状态：应用 flow=scrolled、SDK 偏好 scroll=true、正文 CSS readium-scroll-on，但内部 layout=reflowable，当前模块列表仍含 column_snapper。竖直手势存在约 20px 自然横向偏移，正文 0→327px 后，旧分页模块在 touchend 发出 no_less，SDK 进入上一章；该次没有应用层离散翻页命令。

直接原因：传入 SDK 的内存 Manifest 缺少 metadata.conformsTo。固定版本 @readium/shared 2.4.0 在缺少 profile 时将 effectiveLayout 计算为 null；@readium/navigator 2.8.2 初始化仅在有效布局为 reflowable 时采用 scroll 偏好，因此滚动设置重新打开时仍选中分页模块。

修复在 original-publication/local-publication.ts 的唯一 Manifest 装配出口补充 conformsTo: [Profile.EPUB]。EPUB、TXT、FB2、MOBI 家族的内存 XHTML Publication 复用此入口。原件格式和字节不变；显式 fixed 布局保留，缺省 reflowable 由 SDK profile 解释。

证据：

- 真机只读 Metadata 副本补齐 profile 后，SDK 自身 determineLayout(publication, true) 从 reflowable 变为 scrolled。
- 经正常界面 submitPreferences 后加载 scroll_snapper；移除所有正文诊断 CSS 后，用户确认正常滚动。正文 0→332→737→1082px，没有 no_less/no_more。
- 原线上页面重载后，再次读到 scroll=true、effectiveLayout=null、column_snapper，确认初始化反例。
- 新单测修复前失败：预期有效布局 reflowable、实际 null。修复后缺省、reflowable、fixed 三种输入均通过。
- 原生触摸 E2E 修复前检测到竖直上滑误发跨章事件；修复后桌面和手机视口两轮模式切换、重开及带少量横向偏移的竖直上滑通过，正文移动且边界命令数为 0。

body overflow:visible、滚动根 height:100% 的试验均已撤回，没有保留正文 overflow、height、touch-action 兼容覆盖。错误的帧显示时序修改也未保留。

## iPhone PWA 底部空白

设备 CSS 屏幕 440×956。原 Shell fixed+h-dvh 时窗口及 visualViewport 高 894px，100vh 为 956px，100dvh 约 894px。仅改 100vh 保留 fixed，用户反馈空白缩小但底部菜单被遮挡一半，未采用。

改为 absolute+100vh 后，窗口和 visualViewport 随后更新为 956px，用户确认底部空白很小、菜单完整可操作。后续滚动失败复核中，用户也确认菜单完整性没有问题。

app/globals.css 仅对 WebKit standalone 的现有 ReaderShell 应用 position:absolute、height:100vh，保留原安全区与菜单布局。普通浏览器沿用原布局。完整源码测试构建在真机加载后也测得 Shell/窗口均为 956px，但正文运行验收仍未完成。

## 前一阶段保留的修复

- 单击跨章重复翻页：真实无位移单击只有一次 SDK tap，Safari 的兼容 click 被重定向到 iframe 外层，Shell 再导航。reader-shell.tsx 的 shouldIgnoreReaderInteraction 忽略已就绪输入桥容器的外层事件。没有修改 SDK 帧显示顺序。原线上临时因果对照中右、左、右、右四次单击各仅一次导航，跨入长章停在 x=0；该对照不算完整构建验收。
- 滚动点击选中隐藏旧章：readium-adapter.ts 的 currentContentDocument 使用 SDK 公开 pool.currentFrames[0].iframe，检查连接、容器和可见性，取消任意旧 iframe 回退。既有滚动步进和章节边界定位共用此入口。
- 两种模式边距：readium-presentation.ts 将同一 pageGutter 同时映射到 SDK pageGutter、scrollPaddingLeft/Right，修复分页默认各 16px、滚动各 0px 的不一致。

## 最终验证与缺口

受测源码 e517628a 加当前工作区修改。NAS 运行 1.6.0，BUILD_ID HJKeSdAo49yPfglAXUWH-；实际线上相关 SDK/适配器代码已只读核对。真机报告 iPhone18,2、系统 27.0.1，navigator.standalone 和 standalone 媒体查询均为真。

- 2 个桌面/手机视口原生滚动切换与重开 E2E 通过。
- 18 个相关桌面/手机视口 E2E 通过：兼容 click、章节边界、当前文档、边距、居中、触摸点击和设置。
- 29 个适配器、展示映射、滚动步进单测通过。
- Web 类型检查、变更 TypeScript/E2E 文件 ESLint 通过。
- Webpack 完整生产构建通过，BUILD_ID 1yLCp3mPyYHo4WJSL7CHb；构建工具临时改写的 next-env.d.ts、tsconfig.json 已恢复。

完整构建仅通过本机调试会话转发到手机，没有改动 NAS。EPUB 下载完成后卡在创建 SDK navigator 之前；前次 MOBI 测试另遇 MOBI_NOT_FOUND，Windows WebKit 另有 ORIGINAL_CACHE_IO。不能将原线上临时对照、自动化或编译结果当作完整构建真机验收通过。

完整修复构建的 iPhone Safari/PWA 正文、重开、模式切换验收仍待完成。调试转发、临时正文 CSS、事件记录已清除；手机恢复原线上《水星播种》。没有发布。

## 本地完整构建的后续真机反馈

同一 BUILD_ID 的生产模式本地服务现位于 http://192.168.50.179:3101，手机已直接从该地址添加到主屏幕，navigator.standalone=true。没有使用线上脚本替换或网络转发。EPUB 已正常打开，先前调试转发方式卡住的结果不能继续描述为该直接访问方式的现状。

用户最初报告竖直触摸产生顶部空白并弹回，但点击翻页正常。读取该失败反馈后的当前页面：SDK effectiveLayout=reflowable、layout=scrolled，模块列表含 scroll_snapper；没有 column_snapper。因此 profile 修复已生效，但不足以证明这次所有手势反馈已解决。

未修改正文样式或滚动位置，仅开始记录后，用户反馈“现在正常了”。记录确实显示正文上滑 0→421px、反向滑动 421→203px，外层 scrollY 始终为 0。没有证据证明恢复来自新的代码修复；不能据此再添加 overflow/height 补丁或宣称原反馈已消失。继续通过正常设置切换分页/滚动，核对新文档首次手势和松手后的稳定位置。

## 模式切换后的宿主 inert 问题

在完整本地构建 1yLCp3mPyYHo4WJSL7CHb 上重新执行正常“分页→滚动”后，用户复现空白回弹。SDK 始终为 scrolled/scroll_snapper，正文 scrollY=0，外层 scrollY 到 173px 后回弹；没有离散翻页命令。因此不能把正确模块列表视为原生触摸验收通过。

逐项对照结果：

- 宿主改为正常文档流后仍失败，已撤回。
- 两层裁剪从 hidden 改成 clip 后仍失败，已撤回。
- 四层裁剪全部移除时只是外层页面滚到 216px 并露出空白，正文仍为 0，已撤回。
- 同一本书、同一个 SDK、相同正文 CSS 和尺寸，在不经过应用包裹的临时区域里，通过 SDK 接口完成分页→滚动后可以滚动；松手 2 秒仍停在 373px，外层为 0。
- 恢复应用的全部原布局、正文样式和 SDK，只在设置面板打开期间阻止 main 进入 inert，重新通过正常设置完成分页→滚动后，正文 0→425px，松手 2 秒保持 425px，外层始终为 0。用户确认能够停留。

原因在应用接入：面板打开时 main 被置于 inert，切换模式创建的新 Readium iframe 继承该状态；该 iPhone 上撤销 main 的 inert 后，iframe 的原生滚动仍未恢复。初次打开和未经过该状态的独立 SDK 区域可以滚动。

修复仅在 reader-shell.tsx 的现有 main：Readium 宿主不再随面板进入 inert；面板期间使用 aria-hidden 隐藏正文的辅助功能内容，保留已有遮罩、对话框焦点循环和输入阻断。PDF/漫画保留原 inert 行为。没有改 SDK、正文 CSS、手势或添加重绘定时器。

在既有原生滚动 E2E 中补上宿主状态、辅助功能隐藏和 Shift+Tab/Tab 焦点循环断言，保留真实触摸滚动与重开验证。10 个桌面/手机视口相关 E2E 通过，局部 ESLint 通过，完整生产构建及其 TypeScript 检查通过。新 BUILD_ID 为 KiZeTcKnFOJvuXSEeoJ59，本地 3101 服务已更新并由手机脚本确认该身份；诊断观察器及全部试验在刷新时清除。

最终真机验收：关闭 USB 调试会话后，用户在该完整本地构建自行执行“设置→分页→滚动→关闭面板”，上滑并松手等待 2 秒，反馈“本次正常 没有回弹”。该条原失败路径在手机主屏幕 PWA 上通过；不据此宣称其他未复测平台或全量 Reader 行为通过。本地测试服务继续保留，未发布到 NAS。

## v1.6.1 发布准备

- 发布分支：codex/release-v1.6.1，基线为 origin/main 与 origin/develop 共同指向的 b3b684d3，即已发布 v1.6.0 加两次发布时间记录修订。原工作区仍保留其未提交改动，没有直接从 v1.5.6 覆盖正式版本。
- 只移植本次 8 个 Reader 源码/测试文件；逐文件核对与已测试内容一致。其他工作区改动不纳入此补丁，保留 v1.6.0 已有修复。
- 全仓版本标识更新为 1.6.1，移动版本构建号按既有序列递增到 15；没有构建或选择 Android/iOS 安装包。
- 新增 release-notes/v1.6.1.md 的 zh-CN/en-US 修复说明与索引条目。普通服务端发布，不设置 code-only 元数据；计划交付服务端镜像、fnOS 和在线更新包。
- 索引中的时间是准备时填写的预备值，正式公开时须核对实际发布时间；不得把它当作已公开的证据。
- 本次仅准备候选提交，不推送分支、不创建正式标签、不触发正式工作流、不公开 Release、不改 NAS。正式发布前仍须按既有流程对齐远端 main/develop 到发布提交，再从正式标签运行普通发布门禁；本地验收与版本说明校验不替代正式工作流结果。

## v1.6.1 快速发布执行

用户明确授权快速更新，不保留单独发布分支。采用 code-only，baseVersion=1.6.0，基础镜像固定为 gamersgu/shuku-starship-web@sha256:c88bc42b9e33de0ff62b76ab7f49d5a127b2919b74fc27137515cbf34ee29051；两架构 OCI 镜像标签均核对为 v1.6.0 源码 71d52fe2。应用修复和已有定向验收结果不变。发布冻结后将远端 main/develop 快进至同一提交并创建正式标签；不构建或推广 Docker 镜像，不生成 FPK/APK/IPA，正式快速门禁由同一标签工作流执行。前一节的普通发布计划已被本次用户选择取代。

## v1.6.1 快速发布结果

- 正式源码 / tag：3e2608a34f5ffef6014eff5ce7c223386f9a4d54；main/develop 在推送正式标签时同步到该提交，未推送或保留单独发布分支。
- Actions：39969639232，全部本次快速门禁成功；Web 模块检查通过，双架构应用构建与依赖身份/产物校验通过，GHCR 上传及所有 blob 匿名校验通过。
- 不可变 bundle artifact：12508807642，sha256:02c45b8485189908f66129216c55c127441eb9f2dc7b17b1bb05b6a21b3649cd。
- linux-x86_64 OCI：sha256:3c4e67aff5d62d01ded3f3d8ad848b7b852fc79a6071bcc24f126b2c2ff86410；linux-aarch64 OCI：sha256:a23ab242eb32e10678ea44abd368873f3559a8e5624d456c5475ff1cee14f1cd。
- GitHub Release 实际公开时间：2026-10-23T14:41:20Z；release-feed 已含 1.6.1 和两架构固定引用。当前补记只校准时间与结果，不修改已公开标签及制品；元数据提交使用 skip ci 避免标签后的普通开发镜像构建。
- 本次运行总体 15 分 53 秒；发布预检 53 秒，双架构构建步骤 10 分 23 秒，候选 job 11 分 7 秒，汇总 50 秒，发布 job 2 分 53 秒，其中 GHCR 上传与匿名校验 1 分 19 秒。后端完整测试、镜像构建/运行验收、移动检查/安装包按 code-only 计划跳过。未运行的新平台/安装验收不宣称通过；未执行 NAS 更新安装。无 Docker 构建缓存收益可报告，未以并行或缓存估算节省时间。
