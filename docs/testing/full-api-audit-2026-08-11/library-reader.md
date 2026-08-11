# 书库、媒体、书架与 Reader API 报告

- OpenAPI operations：87
- 覆盖：87/87
- 真实 TCP 请求：113（包含 Range、下载、writer-lock、空 body 契约变体）
- 分布：library 47、media 10、shelf 5、Reader v1 retired 13、Reader v2 retired 7、Reader v3 5
- 逐 operation：见[总执行矩阵](./api-operation-matrix.md)

## 数据库与事务断言

- 作品更新、批量查找替换、封面、元数据应用、分类 merge/rename/delete 和卷册结构操作均核对目标行、关系表及 operation/undo 数据。
- Shelf 与 ShelfWork 集合创建/替换/删除保持原子。
- 文件 HEAD/GET 200，Range GET 206 且字节头正确；Work volume archive 返回真实 ZIP，GET 不修改数据库。
- Reader v3 bootstrap 只读；progress/status/bookmarks 分别验证 Progress、History、Bookmark，且 Work/Volume.updatedAt 不变。
- Reader v1/v2 的 20 个退役契约均返回 410，数据库零变化。
- writer lock 下 works、facets、shelves、Reader v3 bootstrap 均在 2–11ms 返回，SQLAlchemy 快照无变化。
- 最终孤儿记录为 0，12/12 个 `LibraryFile` 引用路径存在。

## 首轮缺陷与修复结果

以下问题均已修复，并在全新实例重新覆盖 87/87、113/113 次真实请求；详见[修复复测报告](./library-media-shelf-fix-rerun.md)。

### P0：漫画 pages GET 隐式写数据库（已修复）

新导入 CBZ 尚无 reading units 时，`GET /api/volumes/{volume_id}/pages` 会解析文件、插入 `LibraryReadingUnit` 并修改 `LibraryVolume.updatedAt`。

独立 Engine 持有 writer lock 时：

- 请求等待 10,695.86ms 后 raw 500；
- 锁内 units 仍为 0、updatedAt 不变；
- 释放锁后重试 200/7.25ms，units 0→2，Volume.updatedAt 改变。

这条链路仍把文件解析和维护写入放在 GET 中，应迁移到导入完成阶段或独立维护 Worker。

最终兼容链路改为“读取投影并关闭 Session → 事务外只读解析 archive → 返回 DTO”，锁下 1.86ms/200，数据库零变化。OPDS 使用同一只读端口。

### P1：OpenAPI body/response 描述不完整（已修复）

11 个 library/shelf 操作实际消费 body，但 OpenAPI 没有 `requestBody`。严格按文档发送空 body 时，10 个抛出未捕获 `JSONDecodeError` 并返回 raw 500，一个返回 400；所有探针均无 DB 变化。提供合法 body 后 happy path 均成功。

此外，`POST /api/shelves` 的实际 201，以及两个文件 Range GET 的实际 206，未列入 OpenAPI response。

最终 11 个接口均有显式 request model，空 body 全部 422；201/206 已进入 OpenAPI。

## 原始证据

- 汇总：`/tmp/shuku-api-audit-library-reader-POGX9K/reports/README.md`
- 逐请求结果：`/tmp/shuku-api-audit-library-reader-POGX9K/reports/runtime-results.json`
- pages 锁冲突：`/tmp/shuku-api-audit-library-reader-POGX9K/reports/media-pages-writer-lock.json`
- 完整性：`/tmp/shuku-api-audit-library-reader-POGX9K/reports/final-db-integrity.json`
- 分模块文档：同目录 `library.md`、`media.md`、`shelf.md`、`reader-v1-retired.md`、`reader-v2-retired.md`、`reader-v3.md`
