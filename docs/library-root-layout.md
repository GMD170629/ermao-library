# 书库根目录结构 / Library Root Layout

## 中文

每个书库配置一个根目录和一种组织方式。扫描器只发现受支持的文件；领域解析器每次只接收
一个相对于书库根目录的文件路径。同一组织方式下，同一路径始终得到相同的作品、版本、卷
和来源键，不读取同级目录、扫描批次、数据库记录或媒体元数据。

### 单本（FLAT）

每个受支持文件都是一本独立作品。扫描会递归进入任意目录，但目录名称不形成作品层级：

```text
books/
├── 活着.epub                  -> 作品“活着”
└── 科幻/中文/三体.pdf         -> 作品“三体”
```

每个作品包含一个隐式版本和一个同名卷。

### 卷册（VOLUMES）

根目录文件独立成书；第一级目录是作品，第二级目录是版本。第二级之后不再解析目录层级，
每个受支持文件独立成卷：

```text
books/
├── 活着.epub                         -> 作品“活着”/隐式版本/卷“活着”
└── 三体/
    ├── 01 地球往事.epub              -> 作品“三体”/隐式版本/卷“01 地球往事”
    └── 中文版/精校/02 黑暗森林.epub   -> 作品“三体”/版本“中文版”/卷“02 黑暗森林”
```

卷来源键保留完整相对文件路径，因此不同深层目录中的同名文件仍是不同卷。

### 有声书（AUDIOBOOK）

根目录音频文件独立成书。第一级目录是作品；作品之后忽略 `CD`、`Disc`、`Disk`、`碟`、
`盘` 及其编号形式，再把第一个普通目录作为版本、第二个普通目录作为卷。其余更深目录不再
形成业务层级：

```text
audiobooks/
├── 魔戒.m4b                         -> 作品“魔戒”/隐式版本/卷“魔戒”
└── Book/
    ├── CD1/01.mp3                   -> 作品“Book”/隐式版本/默认卷“Book”
    ├── V1/CD2/02.mp3                -> 作品“Book”/版本“V1”/默认卷“V1”
    └── V1/Vol1/CD3/03.mp3           -> 作品“Book”/版本“V1”/卷“Vol1”
```

解析到相同卷来源键的音频文件都归入该卷，并按完整相对路径自然排序。单个有声书扫描最多
接受 10,000 条音轨。

所有模式均直接读取原始文件，不生成派生出版物。文件元数据可以补充作者、封面、简介和
音轨标签，但不能改变路径确定的作品、版本、卷、名称或来源键。实时监听和定时扫描由系统
设置控制；仅在尚未保存扫描间隔时使用 `LIBRARY_SCAN_INTERVAL_MS` 作为兼容回退。所有触发
使用相同的有界队列。新规则不自动迁移、合并
或删除已经导入的旧拓扑。

## English

Each library has one root and one organization mode. The scanner only discovers supported
files, and the domain parser receives one library-relative file path at a time. Under the
same mode, the same path always produces the same Work, Version, Volume, and source keys;
sibling entries, scan batches, database state, and embedded metadata are not inputs.

- `FLAT`: every supported file is an independent Work, regardless of directory depth. It
  receives an implicit Version and one same-named Volume.
- `VOLUMES`: a root file is an independent Work. The first directory is the Work and the
  second is the Version. Every supported file is a separate Volume; deeper directories do
  not create more topology. The complete relative file path remains part of the Volume key.
- `AUDIOBOOK`: a root audio file is independent. After the Work directory, transparent
  `CD`, `Disc`, `Disk`, `碟`, and `盘` directories are ignored. The first remaining directory
  is the Version and the second is the Volume. Files with the same Volume key aggregate as
  tracks and use natural ordering by complete relative path.

Every mode reads original files without producing a derived publication. Metadata may enrich
authors, covers, descriptions, and track tags, but it cannot change path-owned topology,
names, or keys. Periodic and manual scans use the same bounded queue. These rules apply to
newly discovered sources and do not automatically migrate existing imported topology.
