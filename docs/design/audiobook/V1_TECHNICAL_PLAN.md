# 二毛图书有声书与多媒介书目 V1 技术方案

> 状态：V1 已按确认的“下划线多媒介选项卡”方案实现，并完成自动化、真实音频链路与浏览器视觉验收
> 制定日期：2026-07-20
> 适用范围：桌面 Web、移动 Web 与 PWA；后端 FastAPI、SQLite、持久化导入 Worker
> 核心目标：一个 `LibraryWork` 下可以同时拥有电子书、漫画和有声书，并分别阅读、播放和保存进度

## 1. 结论与关键决策

现有 `LibraryWork → LibraryEdition → LibraryVolume → LibraryFile / LibraryReadingUnit` 层级继续保留，不另建一套孤立的有声书库。

本次改造的关键是把“作品是什么类型”调整为“作品拥有哪些媒介版本”：

- `LibraryWork` 只表达统一书目身份：标题、作者、简介、标签、系列、封面。
- `LibraryEdition.mediaKind` 表达媒介类别：`EBOOK`、`COMIC`、`AUDIOBOOK`。
- `LibraryEdition.format` 表达阅读器格式：`EPUB`、`PDF`、`COMIC`、`AUDIO`。
- `LibraryFile` 保存实际容器与 MIME：M4B/M4A 使用 `audio/mp4`，MP3 使用 `audio/mpeg`。
- 每个媒介类别有自己的主版本、最近使用版本、消费状态和进度。
- `LibraryWork.workType` 与 `primaryEditionId` 暂时保留为兼容字段，但不再作为新功能的事实来源。
- 图书详情不新增独立的有声书信息架构；现有“目录 / 内容结构”升级为“电子书 / 漫画 / 有声书 / 内容结构”。
- 媒介选项卡是详情页的消费上下文开关：切换时同步替换媒介摘要、进度、位置、状态、主按钮和目录内容。
- 不存在的媒介不渲染选项卡；可见顺序由后台系统设置决定；用户最后一次选择按用户与图书保存。

这一模型让同一条目下可以出现：

```text
《三体 II：黑暗森林》
├── EBOOK
│   ├── EPUB 人民文学出版社版
│   └── PDF 扫描版
├── COMIC
│   └── 漫画版 1–12 卷
└── AUDIOBOOK
    ├── 完整有声版 · 朗读者 A · M4B
    └── 广播剧版 · 朗读者 B · MP3 分轨
```

## 2. 产品边界

### 2.1 V1 必须支持

- 从现有手动上传入口导入单文件 M4B、M4A、MP3。
- 从监控文件夹识别单文件或多分轨有声书目录。
- 下载任务产出支持格式后继续走现有自动导入管线。
- 提取书名、作者、专辑、朗读者、时长、轨号、碟号、章节和封面。
- 根据书名与作者合并到已有电子书或漫画条目。
- 播放、暂停、拖动、前后跳转、切章、切轨、倍速、音量和睡眠定时。
- 有声书进度与 EPUB、PDF、漫画进度相互独立。
- 只保留跨页面常驻的全局迷你播放器；章节、倍速、音量和睡眠定时等完整播放能力全部由迷你播放器承载。
- 桌面、移动浏览器和 PWA 使用同一播放状态。
- 锁屏、通知中心和耳机按键通过 Media Session 渐进增强。

### 2.2 V1 不承诺

- DRM 有声书。
- Audible AAX/AAXC 解密。
- 在线音乐式播放队列和跨书连续播放。
- 自动下载远程有声书来源；现有来源若能下载受支持文件则可以自动入库。
- 大文件离线缓存；V1 默认只在线播放，显式离线下载后续实现。
- FLAC、OGG、OPUS、WMA 等格式的浏览器兼容播放。
- 服务器自动转码；V1 先识别并明确报告不兼容编码，后续增加转码队列。
- 电子书章节与音频章节的自动语义对齐。

## 3. 现状与需要解除的旧假设

当前代码已经具备以下基础：

- 导入器使用书名和作者生成跨格式 `mergeKey`。
- EPUB、PDF 和漫画可以成为同一个 `LibraryWork` 下的不同 `LibraryEdition`。
- 文件接口已经实现字节 Range、206、ETag 和受控文件访问。
- Reader V2 已有统一 bootstrap、内容指纹、位置模型、进度同步和离线提交队列。
- `AppShell` 位于全站根部，可以承载跨路由持续存在的音频实例。

需要解除的假设：

1. `LibraryWork.workType` 只能表示一个类型。
2. 整个 Work 只有一个 `primaryEditionId`。
3. `WorkView` 顶层只能返回 ebook 或 comic。
4. Reader V2 bootstrap 只能表达 epub、pdf、comic；视觉阅读器核心本身仍保持这三类 ReaderKind。
5. Reader V2 的共享进度位置只能表达 CFI、页码或漫画页。
6. `LibraryWork.status` 会被任意版本完成事件直接改成 `FINISHED`。
7. 导入任务以单文件为单位，无法把数十条 MP3 表达为一个整书任务。
8. Service Worker 的大文件绕过规则没有覆盖音频文件。

## 4. 领域模型

### 4.1 媒介与格式

```ts
export type MediaKind = 'EBOOK' | 'COMIC' | 'AUDIOBOOK';
export type ReadingFormat = 'EPUB' | 'PDF' | 'COMIC' | 'AUDIO';
```

映射规则：

| 文件或容器 | `mediaKind` | `format` | 文件 MIME |
| --- | --- | --- | --- |
| EPUB / 转换后的 EPUB | EBOOK | EPUB | application/epub+zip |
| PDF | EBOOK | PDF | application/pdf |
| CBZ / 图片 ZIP | COMIC | COMIC | application/vnd.comicbook+zip / application/zip |
| M4B / M4A | AUDIOBOOK | AUDIO | audio/mp4 |
| MP3 | AUDIOBOOK | AUDIO | audio/mpeg |

### 4.2 层级语义

- Work：跨媒介书目身份。
- Edition：一个可独立选择的发行或制作版本，例如不同出版社、扫描版、朗读者或广播剧版。
- Volume：同一 Edition 下的卷、部或册。
- File：实际读物文件；有声书可有一个 M4B 或多个 MP3。
- ReadingUnit：章节、页面或音频时间片。

音频章节必须引用 `fileId`，并保存 `startMs` 和 `endMs`。如果文件没有章节：

- 单个音频文件生成一个覆盖整段时长的章节。
- 多分轨版本默认每个文件生成一个章节。
- MP3 内嵌 ID3 `CHAP` 或 M4B 内嵌章节时，再细分为多个时间片。

## 5. 数据库 v4

迁移继续使用当前“迁移前自动备份 → 事务迁移 → schema.sql 幂等补齐”的机制。

### 5.1 `LibraryEdition`

新增：

```sql
mediaKind TEXT NOT NULL DEFAULT 'EBOOK'
durationMs INTEGER NULL
trackCount INTEGER NULL
narrator TEXT NULL
abridged INTEGER NULL
```

回填：

```text
format = COMIC       → mediaKind = COMIC
format = EPUB / PDF  → mediaKind = EBOOK
format = AUDIO       → mediaKind = AUDIOBOOK
```

`primary` 改为同媒介内主版本。迁移和 Edition 写入逻辑保证：只要某个 `(workId, mediaKind)` 存在未隐藏 Edition，该组就恰有一个可见主版本；部分唯一索引负责阻止同组出现多个可见主版本：

```sql
CREATE UNIQUE INDEX LibraryEdition_workId_mediaKind_primary_key
ON LibraryEdition(workId, mediaKind)
WHERE primary = 1 AND hidden = 0;
```

旧 `LibraryWork.primaryEditionId` 保持原值，作为旧客户端默认打开版本。新 API 优先使用媒介组的主版本。

### 5.2 `LibraryVolume`

新增：

```sql
durationMs INTEGER NULL
```

### 5.3 `LibraryFile`

新增：

```sql
durationMs INTEGER NULL
codec TEXT NULL
bitrate INTEGER NULL
sampleRate INTEGER NULL
channels INTEGER NULL
discNumber INTEGER NULL
trackNumber INTEGER NULL
```

### 5.4 `LibraryReadingUnit`

新增：

```sql
startMs INTEGER NULL
endMs INTEGER NULL
durationMs INTEGER NULL
```

音频单元：

```json
{
  "unitType": "audio_chapter",
  "title": "第 18 章 猜疑链",
  "fileId": "file_xxx",
  "startMs": 3845000,
  "endMs": 4219000,
  "sortOrder": 18000
}
```

`href` 在兼容期继续写入 `audio:{fileId}#t={startSeconds},{endSeconds}`，新播放器以显式字段为准。

### 5.5 `LibraryConsumptionState`

新增用户与媒介级状态：

```sql
CREATE TABLE LibraryConsumptionState (
  id TEXT PRIMARY KEY,
  userId TEXT NOT NULL,
  workId TEXT NOT NULL,
  mediaKind TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'UNREAD',
  lastEditionId TEXT NULL,
  lastVolumeId TEXT NULL,
  lastUnitId TEXT NULL,
  createdAt TEXT NOT NULL,
  updatedAt TEXT NOT NULL,
  FOREIGN KEY (userId) REFERENCES User(id) ON DELETE CASCADE,
  FOREIGN KEY (workId) REFERENCES LibraryWork(id) ON DELETE CASCADE,
  FOREIGN KEY (lastEditionId) REFERENCES LibraryEdition(id) ON DELETE SET NULL,
  FOREIGN KEY (lastVolumeId) REFERENCES LibraryVolume(id) ON DELETE SET NULL,
  FOREIGN KEY (lastUnitId) REFERENCES LibraryReadingUnit(id) ON DELETE SET NULL
);

CREATE UNIQUE INDEX LibraryConsumptionState_user_work_media_key
ON LibraryConsumptionState(userId, workId, mediaKind);
```

规则：

- 打开某媒介时，只更新该媒介状态。
- 一个有声书完成时不能覆盖电子书或漫画状态。
- `LibraryWork.status` 在兼容期只做汇总投影，不作为新 UI 的唯一依据。
- 新“在读”筛选匹配任一媒介 `READING`。

### 5.6 `WorkDetailPreference`

详情页选项卡选择属于用户级、图书级偏好，不放入 `LibraryWork`，也不复用阅读器排版偏好：

```sql
CREATE TABLE WorkDetailPreference (
  id TEXT PRIMARY KEY,
  userId TEXT NOT NULL,
  workId TEXT NOT NULL,
  selectedTab TEXT NOT NULL,
  createdAt TEXT NOT NULL,
  updatedAt TEXT NOT NULL,
  FOREIGN KEY (userId) REFERENCES User(id) ON DELETE CASCADE,
  FOREIGN KEY (workId) REFERENCES LibraryWork(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX WorkDetailPreference_user_work_key
ON WorkDetailPreference(userId, workId);
```

`selectedTab` 允许 `EBOOK`、`COMIC`、`AUDIOBOOK`、`STRUCTURE`。服务端读取时必须重新校验可见性：

1. 记忆项仍可见时直接选中。
2. 记忆的媒介已被删除或隐藏时，选择后台排序后的第一个可用媒介。
3. 作品暂时没有可消费媒介时，回退到 `STRUCTURE`。

全局选项卡顺序复用现有 `SystemSetting`，键为 `workDetail.tabOrder`，值为包含四个 tab key 的 JSON 数组。写入时去重、剔除未知值，并补齐遗漏项；默认值为：

```json
["EBOOK", "COMIC", "AUDIOBOOK", "STRUCTURE"]
```

### 5.7 `ImportAsset`

为了把多分轨有声书表现为一个任务，新增任务资产表：

```sql
CREATE TABLE ImportAsset (
  id TEXT PRIMARY KEY,
  importTaskId TEXT NOT NULL,
  sourcePath TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING',
  sortOrder INTEGER NOT NULL DEFAULT 0,
  fileId TEXT NULL,
  errorCode TEXT NULL,
  errorSummary TEXT NULL,
  createdAt TEXT NOT NULL,
  updatedAt TEXT NOT NULL,
  FOREIGN KEY (importTaskId) REFERENCES ImportTask(id) ON DELETE CASCADE,
  FOREIGN KEY (fileId) REFERENCES LibraryFile(id) ON DELETE SET NULL
);
```

`ImportTask` 新增：

```sql
taskKind TEXT NOT NULL DEFAULT 'FILE'
bundleKey TEXT NULL
assetCount INTEGER NOT NULL DEFAULT 1
processedAssetCount INTEGER NOT NULL DEFAULT 0
```

## 6. API 契约

### 6.1 WorkView V2

现有顶层 `formatValue`、`editions` 和 `volumes` 在兼容期保留，同时新增媒介分组：

```ts
type WorkMediaGroup = {
  kind: 'EBOOK' | 'COMIC' | 'AUDIOBOOK';
  primaryEditionId: string | null;
  recentEditionId: string | null;
  recentVolumeId: string | null;
  status: 'UNREAD' | 'READING' | 'FINISHED';
  progress: number;
  positionLabel: string;
  durationMs: number | null;
  chapterCount: number | null;
  volumeCount: number;
  editions: EditionView[];
};

type WorkViewV2 = WorkView & {
  defaultMediaKind: MediaKind | null;
  availableMediaKinds: MediaKind[];
  mediaGroups: WorkMediaGroup[];
  detailTabs: WorkDetailTab[];
  selectedDetailTab: WorkDetailTabKey;
};

type WorkDetailTabKey = MediaKind | 'STRUCTURE';

type WorkDetailTab = {
  key: WorkDetailTabKey;
  label: '电子书' | '漫画' | '有声书' | '内容结构';
  sortOrder: number;
};
```

默认选项卡选择：

1. `WorkDetailPreference.selectedTab` 仍可见时使用记忆值。
2. 否则使用系统排序后的第一个可用媒介。
3. 没有可用媒介时使用 `STRUCTURE`。

媒介选项卡仅在对应 `mediaGroups` 至少有一个未隐藏 Edition 时返回；`STRUCTURE` 始终返回。前端不自行猜测顺序或可见性。

### 6.2 详情页上下文 API

首屏请求返回全部媒介摘要，但只展开当前选项卡的目录数据，避免同时装载 EPUB 章节、漫画卷册和音频轨道：

```text
GET /api/works/{workId}?detailTab=AUDIOBOOK&volumeId=...&unitPage=1
PUT /api/works/{workId}/detail-preference
```

偏好写入请求：

```json
{ "selectedTab": "AUDIOBOOK" }
```

`detailTab` 是一次显式查看，不依赖写偏好完成后才能切换。前端切换流程为：

1. 立即切换选中态并显示对应媒介摘要骨架。
2. 并行请求该媒介的目录数据与保存用户偏好。
3. 旧请求通过 `AbortController` 取消或按 request token 丢弃，避免快速切换串数据。
4. 加载失败只影响内容区；选项卡、作品信息和其他媒介仍可操作。

响应中的 `activeMedia` 是详情页唯一消费上下文：

```ts
type ActiveWorkMedia = {
  key: MediaKind;
  formatLabel: string;
  selectedEditionId: string | null;
  selectedEditionName: string | null;
  status: 'UNREAD' | 'READING' | 'FINISHED';
  progress: number;
  positionLabel: string;
  primaryAction: {
    label: '开始阅读' | '继续阅读' | '开始看' | '继续看' | '开始听' | '继续听';
    href: string;
  } | null;
  units: ReadingUnitView[];
  volumes: VolumeView[];
};
```

切到 `STRUCTURE` 时 `activeMedia = null`，作品级标题、作者、封面和简介保持不变；媒介进度、阅读状态控件与主消费按钮隐藏，内容区显示全部媒介的版本与卷册管理。

### 6.3 书库筛选

新增：

```text
GET /api/works?mediaKind=AUDIOBOOK
GET /api/works?mediaKinds=EBOOK,COMIC
```

后端通过 `EXISTS LibraryEdition` 查询，不能再使用 `LibraryWork.workType`。

统计按 Work 去重：同一本书拥有三个媒介仍只计一本书。

### 6.4 Reader V2 / Audio bootstrap

保留 `/api/reader/v2/editions/{editionId}/bootstrap`，以向后兼容的可选字段新增 `audio` reader type。bootstrap 与 progress 的 wire schema 继续保持 V2，不因音频能力升级到 wire v3；只有服务端阅读偏好 `serverPreferences` schema 升级到 v3。

```ts
type AudioTrack = {
  fileId: string;
  title: string;
  url: string;
  mimeType: string;
  durationMs: number;
  discNumber: number | null;
  trackNumber: number | null;
  sortOrder: number;
};

type AudioChapter = {
  id: string;
  title: string;
  fileId: string;
  startMs: number;
  endMs: number;
  sortOrder: number;
};

type AudioBootstrap = {
  readerType: 'audio';
  tracks: AudioTrack[];
  chapters: AudioChapter[];
  totalDurationMs: number;
  resumeLocation: AudioProgressLocation | null;
  progressPercent: number;
};
```

音频文件 URL 使用现有受控文件路由：

```text
/api/files/{fileId}
```

### 6.5 AudioProgressLocation

```ts
type AudioProgressLocation = {
  type: 'audio';
  volumeId: string | null;
  fileId: string;
  chapterId: string | null;
  positionMs: number;
};
```

进度百分比按 Edition 的绝对时长计算：

```text
(已完成轨道时长 + 当前轨道 positionMs) / totalDurationMs × 100
```

只有最后一轨的原生 `ended` 事件将进度提交为 100%。不使用“接近 100%”自动完成，避免时长和编码尾部误差。

### 6.6 音频偏好

服务端 `serverPreferences` schema 升级到 v3 并增加以下音频字段；Reader V2 bootstrap/progress wire 仍为 V2：

```ts
audio: {
  playbackRate: number;          // 0.75–3.0
  skipBackwardSeconds: number;   // 默认 15
  skipForwardSeconds: number;    // 默认 30
  volume: number;                // 桌面恢复；移动端由系统控制时忽略
}
```

睡眠定时属于当前播放会话，不写入长期偏好。

## 7. 导入与识别

### 7.1 支持格式策略

V1 接受：

- `.m4b`
- `.m4a`
- `.mp3`

播放器正式保证的编码基线：

- MP3。
- MP4/M4B 容器内 AAC 音频。

导入时记录实际 codec。客户端使用 `HTMLMediaElement.canPlayType` 进行最终能力检测。ALAC、AC-3 或其他编码可以进入“格式不兼容”失败状态，不静默导入为可播放内容。

### 7.2 元数据解析

新增 `app/services/audio_metadata.py`：

- Mutagen 负责常见标签、时长、轨号、碟号、MP4 章节、ID3 CHAP、APIC/covr。
- ffprobe 负责复杂容器的音频流验证、codec 和章节兜底。
- 解析过程只读源文件，不写标签、不覆盖源文件。
- 所有原始标签保存到 `LibraryMetadata(source='audio_tags')`。
- 规范化后的阅读顺序与章节保存到 `LibraryMetadata(source='audiobook_manifest')`。

建议映射：

| 目标字段 | M4B / MP4 | MP3 / ID3 |
| --- | --- | --- |
| title | `©nam` | TIT2 |
| album / work title | `©alb` | TALB |
| author | `©ART` / `aART` | TPE1 / TPE2 |
| narrator | freeform readBy / composer fallback | TXXX:narrator / TCOM fallback |
| track | `trkn` | TRCK |
| disc | `disk` | TPOS |
| cover | `covr` | APIC |
| chapters | MP4 chapters | CTOC / CHAP |

### 7.3 身份识别优先级

1. 用户在上传对话框明确填写的书名和作者。
2. 文件夹内一致的 album / album artist。
3. 单文件内嵌 title / author。
4. 父目录 `[书名][作者]` 或 `作者/书名`。
5. 当前文件名正则识别。
6. 现有 OpenAI-compatible AI 兜底识别。

`mergeKey` 继续只使用规范化标题和作者，不加入媒介类型或朗读者。因此电子书、漫画和有声书可以命中同一个 Work。

朗读者、出版社、语言、删节状态用于区分 Edition，不参与 Work 身份。

### 7.4 多分轨打包

监控 Worker 遇到音频事件时：

1. 计算最近的音频 bundle root。
2. 对目录变更 debounce，避免每个文件立刻创建一条任务。
3. 先用共享书籍身份规则解析目录名中的书名、内嵌作者和卷号，再判断单卷或多卷边界。
4. `CD1/CD2`、`Disc 1/Disc 2` 只作为物理分轨层；匹配分卷命名或包含上级书名的目录作为业务卷。
5. 创建一个 `AUDIO_BUNDLE` ImportTask 和多个 ImportAsset。
6. 建立或复用 AUDIOBOOK Edition。
7. 按卷、disc、track、自然文件名排序。
8. 为每个业务卷写入独立 `LibraryVolume`，并关联文件、章节、时长和封面。
9. 全部资产成功后将 Edition 和 ImportTask 标为完成。

推荐目录：

```text
/monitor/audiobooks/[鬼吹灯][天下霸唱]/
├── cover.jpg
├── Vol.1/
│   ├── 01-序章.mp3
│   └── 02-精绝古城.mp3
└── 鬼吹灯之龙岭迷窟/
    ├── Disc 1/
    │   └── 01-龙岭.mp3
    └── Disc 2/
        └── 01-迷窟.mp3
```

单卷仍使用 `书名/音轨` 或 `书名/Disc 1/音轨`。目录名中的内嵌作者会被解析，但独立的
`作者/书名/音轨` 层级不再用于推断作者；未匹配分卷规则的子目录按独立有声书继续扫描。

### 7.5 手动上传

- 单个 M4B/M4A/MP3：继续使用现有上传路径。
- 多个音频文件：上传 UI 支持一次选择并默认合并为一本有声书。
- 用户可以为整组音频选填明确的书名和作者，这两个显式值优先于文件标签和路径推断。
- 后端在目标目录下创建安全的书目子目录，再生成 bundle task。
- 后端负责格式、codec、元数据一致性和稳定排序校验；失败任务保留可理解的错误信息与可重试、可整理入口，不静默混合不一致 album。
- V1 不包含上传前的完整元数据预览；标题、作者、朗读者、总时长和排序的富预检界面列入后续增强。

### 7.6 大文件与重复识别

音频文件通常远大于 EPUB，导入主事务不能先计算完整 SHA-256。

采用：

- 立即 fingerprint：真实路径哈希、size、mtime、头部和尾部采样。
- 只有采样 fingerprint 命中已有候选时，才对候选与新文件计算完整 SHA-256 进行最终确认；普通首次导入不计算后台 fullHash。
- `LibraryFile.path`、`filePathHash` 继续防止同路径重复。
- bundle 内相同大小与采样 fingerprint 的文件进入碰撞候选，最终以完整 SHA-256 判断是否重复，避免采样碰撞误删不同文件。

## 8. 播放架构

### 8.1 复用现有 Range 文件服务

音频继续使用 `_file_response`：

- `Accept-Ranges: bytes`
- `206 Partial Content`
- `Content-Range`
- `ETag`
- 登录态鉴权
- 每用户并发流限制

新增音频验收：

- HEAD/GET 元数据请求正确。
- 开始播放不会读取完整文件。
- 拖动后产生合理 Range 请求。
- 416 与文件变化可以恢复。
- M4B 大于 2 GB 时不溢出。

### 8.2 视觉阅读器边界与共享进度域

音频不作为 `AudioAdapter` 塞入 `@shuku/reader-core`。视觉阅读器核心继续只管理 EPUB、漫画与 PDF，避免把长期存在、可跨路由播放的媒体生命周期绑定到单页 Reader 实例。

Reader V2 的共享 bootstrap/progress 领域以可辨识联合扩展音频位置，供服务端进度高水位、离线队列与多设备同步复用：

```ts
type ReaderProgressLocation =
  | EpubProgressLocation
  | PdfProgressLocation
  | ComicProgressLocation
  | AudioProgressLocation;
```

音频 bootstrap 仍从 Reader V2 API 获取，但播放命令、原生媒体事件、文件切换、绝对时间与当前章节均由根级 `AudioPlaybackProvider` 负责。浏览器不支持 codec 时也由该 Provider 提供可理解的错误与重试入口。

### 8.3 全局播放 Provider

新增 `AudioPlaybackProvider`，放在根布局或 AppShell 外层，使图书详情、首页、书库页面以及旧链接兼容入口共享一个 `<audio>` 实例。

Provider 状态：

```ts
type AudioPlaybackState = {
  lifecycle: 'idle' | 'loading' | 'ready' | 'playing' | 'paused' | 'error';
  workId: string | null;
  editionId: string | null;
  track: AudioTrack | null;
  chapter: AudioChapter | null;
  positionMs: number;
  durationMs: number;
  absolutePositionMs: number;
  totalDurationMs: number;
  playbackRate: number;
  skipBackwardSeconds: number;
  skipForwardSeconds: number;
  volume: number;
  sleepTimerEndsAt: number | null;
  sleepTimerMode: 'timer' | 'chapter' | null;
};
```

全局迷你播放器是唯一正式播放界面，只调用 Provider，不自行创建第二个 audio 元素。它提供以下两层能力：

- 常驻控制条：作品/章节信息、播放/暂停、前后跳转、上一章/下一章和进度拖动。
- 向上展开的章节与设置面板：章节/轨道选择、倍速、音量、睡眠定时及其剩余时间。

“开始听”“继续听”、章节行的“收听”及内容结构中的音频入口，都在当前页面的用户手势内直接调用 Provider 启动对应 Edition 或章节，并立即显示迷你播放器；这些内部入口不切换路由。迷你播放器的信息区是进入作品上下文的链接，播放按钮、进度、章节和设置等控制区必须独立处理交互，不触发详情页跳转。

### 8.4 路由

- EPUB、PDF、漫画继续使用 `/reader/{editionId}`。
- 有声书不再拥有新的独立播放页或内部正式播放路由；所有新入口直接打开全局迷你播放器。
- 点击迷你播放器的信息区进入 `/works/{workId}?detailTab=AUDIOBOOK&editionId={editionId}`，确保详情页同步选择有声书标签和当前音频版本。
- 旧 `/listen/{editionId}` 仅作为历史链接兼容入口：解析旧的章节/轨道参数、把目标交给全局 Provider 后，立即替换为上述图书详情 URL；产品内不再生成新的 `/listen` 链接。

### 8.5 Media Session

设置：

- `MediaMetadata.title`：当前章节。
- `MediaMetadata.artist`：朗读者或作者。
- `MediaMetadata.album`：书名。
- artwork：作品或 Edition 封面。
- action handlers：play、pause、seekbackward、seekforward、seekto、previoustrack、nexttrack、stop。
- `setPositionState`：时长、位置、倍速。

API 不可用或部分 action 不支持时，播放器本身仍正常工作。

### 8.6 多标签页

使用 BroadcastChannel：

- 新标签页开始播放前广播 `claim-playback`。
- 其他标签页收到后暂停并保存进度。
- 同一标签页内路由切换不会触发暂停。
- 浏览器不支持 BroadcastChannel 时使用 `storage` 事件降级。

## 9. 进度与同步

保存时机：

- 播放期间每 15 秒。
- pause。
- seeked。
- 切章或切轨之前。
- playbackRate 变化后。
- visibilitychange 到 hidden。
- pagehide。
- ended。

保存策略：

- 高频 timeupdate 只更新内存，不直接请求服务器。
- 同一 mutation 使用现有 clientSequence 高水位机制。
- 离线时复用现有 IndexedDB progress queue。
- 新 `AudioProgressLocation` 必须加入序列化、私有数据清理和浏览器迁移测试。
- 文件指纹改变后不恢复旧 position，返回明确的 fingerprint mismatch。

## 10. PWA 与缓存

V1：

- `.mp3`、`.m4a`、`.m4b` 加入大阅读载荷识别。
- 音频 GET 绕过 Service Worker Cache Storage。
- bootstrap 与进度接口继续 network-first / offline queue。
- 退出账号时清理所有有声书私有进度和播放状态。
- 应用更新前暂停并保存当前音频位置。

后续离线下载必须是显式能力：

- 用户主动选择某一本有声书下载。
- 显示预计空间与实际下载进度。
- 支持取消和移除。
- 绑定当前用户，退出登录后清除私有缓存。
- 不复用普通 app-shell cache。

## 11. 安全与可靠性

- 所有音频路径继续经过 `_stored_path` 与监控根目录边界检查。
- 不接受上传文件名中的路径穿越。
- ffprobe 以参数数组启动，不拼接 shell 命令。
- 解析设置超时、输出大小和最大章节数。
- 封面提取限制像素、格式和文件大小。
- 不写入或修复用户源文件。
- 不允许远程 manifest 直接读取任意 URL；V1 manifest 只引用本地受控 fileId。
- 音频流保持鉴权、Range 校验、并发限制和慢请求日志。

建议限制：

- 单文件最大 8 GiB，可通过配置覆盖。
- 单个 bundle 最大 1000 个音频文件。
- 单文件最多 10000 个章节。
- ffprobe 单文件超时 60 秒。
- 嵌入封面最大 20 MiB，解码后最大 40 MP。

## 12. 兼容迁移

迁移顺序：

1. schema v4 备份。
2. 添加新列和表。
3. 回填 Edition.mediaKind。
4. 保持现有全局 primary Edition，同时给每个新增媒介选择自己的 primary。
5. 从现有 progress 回填 EBOOK/COMIC ConsumptionState。
6. 发布返回 `mediaGroups` 的兼容 API。
7. 前端书库、首页和详情切换到媒介组。
8. 停止以 `workType` 做筛选、统计和阅读器分派。
9. 稳定一个版本周期后再评估删除旧字段；V1 不删除。

回滚：

- 旧应用忽略新增表和列。
- 新增音频 Edition 对旧应用不可读，但不影响 EPUB/PDF/漫画记录。
- 数据库迁移失败使用自动迁移前备份恢复。

## 13. 分阶段落地

### Phase 0：多媒介数据骨架（已实现）

- schema v4。
- mediaKind 与 ConsumptionState。
- WorkView.mediaGroups。
- 媒介筛选和统计改用 Edition EXISTS。
- 主版本改为同媒介内主版本。
- 跨格式兼容与迁移测试。

验收：现有 EPUB、PDF、漫画行为不变，同一 Work 可以稳定返回 EBOOK 和 COMIC 两个媒介组。

### Phase 1：有声书导入闭环（已实现）

- M4B/M4A/MP3 扩展名。
- Mutagen 与 ffprobe。
- 单文件导入。
- 多分轨 bundle 和 ImportAsset。
- 标题、作者、朗读者、时长、章节、封面。
- 导入任务与待整理状态。

验收：单 M4B、单 MP3、多 MP3 文件夹都能导入并合并到正确 Work。

### Phase 2：播放内核（已实现）

- Reader V2 additive audio bootstrap；bootstrap/progress wire 保持 V2。
- 共享进度域中的 AudioProgressLocation。
- AudioPlaybackProvider。
- Range 播放、切轨、倍速、进度同步。
- 跨标签页互斥。

验收：拖动、刷新、切页、断网恢复和多设备进度不会丢失或覆盖其他媒介。

### Phase 3：产品交互（已实现）

- 把图书详情“目录 / 内容结构”替换为动态的“电子书 / 漫画 / 有声书 / 内容结构”。
- 后台提供选项卡排序设置；详情页按用户与图书记忆最后选项卡。
- 媒介切换同步更新格式与版本摘要、独立进度、当前位置、阅读状态、主按钮和目录内容。
- 仅保留跨页面全局迷你播放器，并将章节/轨道、倍速、音量、睡眠定时和完整进度控制集中到常驻控制条及其向上展开面板。
- “开始听 / 继续听 / 收听 / 章节”入口在当前页面直接启动迷你播放器，不切换路由。
- 迷你播放器信息区进入带 `detailTab=AUDIOBOOK` 与 `editionId` 的图书详情；旧 `/listen/{editionId}` 只做兼容重定向。
- 图书卡媒介提示。
- 多音频选择、可选显式书名/作者，以及后端稳定排序与可修复校验。
- 内容结构按媒介分组，并继续承载版本、主版本和卷册管理。
- Media Session。

验收：用户能从同一个书目条目选择读、看或听，并始终理解当前媒介和进度。

### Phase 4：后续增强

- 上传前的完整元数据、朗读者、总时长与轨道排序预览。
- FLAC/OGG/OPUS 等扩展格式转码。
- 显式离线下载。
- 更丰富的外部有声书来源。
- 电子书与有声书章节手动映射。
- 播放统计和书签。

## 14. 测试矩阵

### 14.1 后端

- schema v3 → v4 迁移与回滚备份。
- 新库 v4 幂等初始化。
- EPUB/PDF/COMIC mediaKind 回填。
- 同标题作者 EPUB、CBZ、M4B 合并为一个 Work、三个媒介组。
- 不同朗读者形成两个 AUDIOBOOK Edition。
- M4B 内嵌章节与封面。
- MP3 ID3 CHAP/APIC。
- 多 MP3 disc/track 排序。
- album 冲突进入待整理。
- 重复路径、采样指纹、完整哈希。
- Range 200/206/416、If-Range、ETag。
- 音频进度不会完成其他媒介。

### 14.2 前端单元测试

- WorkView 媒介分组。
- 详情页动态选项卡可见性与后台排序。
- 用户最后选项卡记忆、已删除媒介回退和无媒介回退。
- 快速切换时旧目录请求不会覆盖新媒介上下文。
- 电子书、漫画、有声书分别投影正确的进度、位置、状态、CTA 与目录。
- 内容结构选项卡隐藏消费控件并展示全部版本管理。
- AudioProgressLocation 序列化。
- 绝对时间与百分比计算。
- 跨文件章节跳转。
- sleep timer。
- 迷你播放器展开面板中的章节、倍速、音量和睡眠定时控制。
- 迷你播放器信息区生成带 `detailTab=AUDIOBOOK` 与 `editionId` 的详情链接，控制按钮不触发导航。
- 旧 `/listen/{editionId}` 兼容入口解析目标并替换为规范详情 URL。
- Media Session action 降级。
- BroadcastChannel claim。
- 离线进度队列。

### 14.3 E2E

- 图书详情只显示实际存在的媒介选项卡，并按后台设置排序。
- 图书详情在电子书、漫画、有声书间切换时，顶部阅读信息、阅读控件和下方目录同步变化。
- 刷新或重新登录后恢复该用户在该图书最后选择的选项卡。
- 删除最后选择的媒介后，详情页稳定回退到第一个可用媒介。
- 点击“继续听”在当前页面直接显示迷你播放器，并恢复正确章节和时间，不切换路由。
- 从章节行或内容结构点击“收听”直接在迷你播放器播放指定目标。
- 迷你播放器提供进度、章节、倍速、音量和睡眠定时的完整控制；点击其信息区进入当前有声书 Edition 的图书详情，点击控制区不导航。
- 打开旧 `/listen/{editionId}` 链接后自动替换为带 `detailTab=AUDIOBOOK` 和 `editionId` 的图书详情 URL。
- 迷你播放器跨首页、书库、详情保持播放。
- 移动端迷你播放器不遮挡底部导航。
- 读取受控 Range 音频。
- 退出登录立即停止播放并清除私有状态。
- Chrome、WebKit 与 PWA standalone 验证。

## 15. V1 完成定义

以下条件同时满足才算完成：

1. 同一标题和作者的 EPUB、漫画、M4B 只出现一个书库条目。
2. 图书详情明确显示三个媒介入口。
3. 每个媒介拥有独立主版本和独立进度。
4. M4B、M4A、MP3 单文件可以从上传、Watcher 或下载完成路径导入。
5. 多 MP3 文件夹作为一个任务、一部有声书导入，并保持稳定顺序。
6. 全局迷你播放器支持播放、暂停、拖动、前后跳转、切章、切轨、倍速、音量与睡眠定时，不再依赖完整播放页。
7. 从任意内部“开始听 / 继续听 / 收听 / 章节”入口启动后，迷你播放器在当前页出现并跨首页、书库与详情持续工作。
8. 刷新、离线恢复和跨设备同步能回到正确位置。
9. 不兼容 codec、损坏文件和元数据冲突都有可理解错误与修复入口。
10. EPUB、PDF、漫画现有阅读器自动化测试无回归。

## 16. 交互设计输入

交互视觉探索必须遵守现有“阅读优先”方向：

- 保持暖象牙白背景、珊瑚橙主色、克制边界和轻量层级。
- 不新增常驻“有声书”主导航，媒介能力首先属于图书条目。
- 一个 Work 只显示一张书卡。
- 选项卡采用已确认的一号方向：动态的“电子书 / 漫画 / 有声书 / 内容结构”纯文字下划线标签。
- 电子书、漫画、有声书切换时必须同步切换格式/版本、独立进度、当前位置、状态、主按钮和目录；作品标题、作者、封面、简介保持稳定。
- “内容结构”是管理上下文，不显示消费进度和阅读/播放主按钮。
- 有声书完整播放能力全部由全局迷你播放器承载；“开始听 / 继续听 / 收听 / 章节”在当前页直接启动播放，不进入独立完整播放器。
- 迷你播放器通过常驻控制条及向上展开的章节、设置面板提供进度、切换、倍速、音量和睡眠定时；跨页面时保持同一播放实例。
- 点击迷你播放器的信息区进入带 `detailTab=AUDIOBOOK` 与当前 `editionId` 的图书详情，播放控制本身不触发跳转。
- 最终桌面视觉对照按设计源图原生尺寸 1487×1058 验收，并同时覆盖响应式与 PWA 行为。
- 生产实现保持确认稿的信息层级：作品信息稳定，媒介消费上下文随标签完整切换。

## 17. 实施与验证记录

V1 已完成实现，最终验收证据如下：

- 后端完整测试：`267 passed, 5 skipped`。
- 前端完整测试：`170 passed`。
- TypeScript 类型检查通过，Next.js production build 通过。
- 真实音频链路通过：Watcher 将两条带标签的真实 MP3 与同名 EPUB、CBZ 合并到同一个 Work；播放器完成 bootstrap、鉴权 Range 播放、跨轨连续播放直至原生 `ended`，并正确提交有声书独立进度与完成状态。
- 浏览器功能验收通过：动态显示四个可用标签、记忆用户与作品的最后选择；有声书 CTA、章节和“收听”入口在用户手势内直接启动全局迷你播放器且不切路由；章节/轨道、倍速、音量、睡眠定时和进度控制均可在迷你播放器完成；点击播放器信息区进入当前有声书版本的图书详情；旧 `/listen` 链接仅做兼容重定向；详情页进度实时投影；“内容结构”隐藏消费状态、进度与 CTA，并展示全部媒介版本。
- 浏览器视觉 QA 通过：最终生产构建与确认的一号下划线标签设计稿按 1487×1058 同屏对照，作品封面与书目信息在媒介切换时保持稳定，音频摘要、控件和章节区随当前媒介一致切换。
