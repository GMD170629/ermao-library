# 书库根目录与资源

每个书库配置一个真实根目录，组织方式只有 `FLAT`（平铺）和 `VOLUMES`（卷册）。有声书通过资源适配器识别，不是第三种组织方式。

## 当前数据关系

- `LibrarySourceNode` 保存扫描发现的物理路径树，中间目录保留为导航节点。
- `LibraryBook` 是图书聚合，锚定一个来源节点。
- `LibraryReadableResource` 是可以独立打开的文件或目录资源，归属于 Book。
- `LibraryResourceAsset` 是资源使用的真实文件；阅读进度归属 `resourceId`，媒体访问使用 `assetId`。

系统不再使用 Version／Volume 作为业务层级。目录名、文件名和相对路径保留原样；元数据可以补充展示信息，但不按标题相似度自动合并物理结构。

## 组织方式

| 方式 | 图书归属 |
| --- | --- |
| `FLAT` | 任意深度识别出的每个资源独立形成 Book，包括文件资源和目录资源。 |
| `VOLUMES` | 根目录的文件资源独立成书；第一级文件夹形成 Book，其内部任意深度的资源归属于该 Book。中间目录不形成版本。 |

例如 `三体/中文版/精校/02.epub` 在 `VOLUMES` 下属于 Book“三体”；`中文版/精校` 是导航目录，`02.epub` 是独立资源。在 `FLAT` 下，该资源独立成书。

有声书普通目录分别划分资源；`CD`、`Disc`、`Disk`、`碟`、`盘` 及编号形式可作为透明音轨目录。普通子目录不会被父级有声书吞并。具体规则见[有声书目录资源边界](adr/0022-audiobook-directory-resource-boundaries.md)。

## 扫描与文件生命周期

首次导入和后续补齐共用“继续导入”。自动扫描保留本轮未发现的历史节点；用户手动扫描只在目录正常遍历完成后清理缺失项。符号链接只记录，不跟随导入。
SourceNode 是扫描快照，不是文件系统实时镜像；移动或重命名不会自动迁移原身份。

已有来源节点的书库不能原地切换组织方式。上传目标必须处于已启用、可写的根目录内。扫描和阅读保留原始文件，不持久化派生 EPUB、ZIP 或解包出版物。

实现入口：

- [组织方式](../apps/api-python/app/modules/library/domain/organization_modes.py)
- [来源节点身份](../apps/api-python/app/modules/library/domain/source_nodes.py)
- [图书归属](../apps/api-python/app/modules/library/domain/book_placement.py)
- [导入能力](../apps/api-python/app/modules/imports)
