# 媒介版本与卷册资源升级 / Media Versions and Volume Resources

## 中文

自本次破坏式升级起，“版本”严格表示媒介版本。每个作品最多包含一个电子书、
一个漫画和一个有声书媒介版本；PDF 属于电子书。媒介版本不再表示出版社、格式、
朗读者或备用副本。

每个独立内容资源都是卷册：一个 EPUB、PDF、MOBI、AZW、AZW3、PRC、FB2、TXT、
CBZ/ZIP 文件各形成一个卷册；有声书单文件、单卷分轨目录和多卷作品中的每个卷目录
各形成一个卷册。`Disc`、`CD`、`Disk` 目录只决定音轨顺序，不创建卷册。卷号可空、
可重复，只用于描述；卷册 ID 是身份，`sortOrder` 是显示与继续阅读顺序。

源格式和转换得到的 EPUB 是两个独立卷册，通过 `derivedFromVolumeId` 关联，阅读进度
互不覆盖。进度和书签只以用户、卷册和内容指纹为作用域。作品和媒介不保存整体百分比；
只有全部可见且已授权卷册都达到 100% 时，才动态显示完成。

导入目录和文件命名继续遵循 Wiki：

- [图书导入指南](https://github.com/GMD170629/ermao-library/wiki/zh-CN-Import-Guide)
- [支持格式](https://github.com/GMD170629/ermao-library/wiki/zh-CN-Supported-Formats)

Reader v3 使用卷册 ID：

- `GET /api/reader/v3/volumes/{volumeId}/bootstrap`
- `PUT /api/reader/v3/volumes/{volumeId}/progress`
- `GET/PUT /api/reader/v3/volumes/{volumeId}/bookmarks`
- `GET /api/volumes/{volumeId}/file`

Reader v2 和 Edition 资源接口返回 HTTP 410。升级采用维护窗口，数据库、API、Web 和
Mobile 必须同时上线。升级前自动生成 SQLite 原始快照；旧应用备份必须先由旧应用恢复，
再升级数据库。新版本应用备份格式为 v3。

## English

Starting with this breaking release, a version means a media version only. A
work may contain at most one e-book, one comic, and one audiobook media version;
PDF belongs to e-book. Publisher, format, narrator, and alternate-copy
differences no longer create versions.

Every independently readable resource is a volume. Each EPUB, PDF, MOBI, AZW,
AZW3, PRC, FB2, TXT, or CBZ/ZIP file is a volume. An audiobook file, a split-track
single-volume directory, or each volume directory in a multi-volume audiobook is
also a volume. `Disc`, `CD`, and `Disk` directories affect track order only.
Volume numbers are optional, repeatable labels; the volume ID is the identity and
`sortOrder` controls display and continue-reading order.

A source resource and its derived EPUB are separate volumes linked by
`derivedFromVolumeId`, with independent progress. Progress and bookmarks are
scoped only by user, volume, and content fingerprint. Works and media versions do
not store aggregate percentages. Completion is projected dynamically only when
every visible, authorized volume reaches 100 percent.

Directory grouping and naming continue to follow the project Wiki. Reader v3 is
volume-first and uses the endpoints listed above. Reader v2 and Edition resource
routes return HTTP 410. Database, API, Web, and Mobile must be deployed together
during a maintenance window. The upgrader creates a raw SQLite snapshot first;
old application backups must be restored by an old application before upgrading.
The new application backup format is v3.
