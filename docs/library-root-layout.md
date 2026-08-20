# 书库根目录结构 / Library Root Layout

## 中文

每个书库都有一个独立根目录和一种组织方式。扫描器只解释相对于根目录的路径；目录和
文件直接决定 Work、Version 与 Volume，元数据不会改变结构。

### 平铺（FLAT）

根目录下每个受支持文件都是一个独立作品，同时拥有一个隐式 Version 和一个 Volume：

```text
books/
├── 活着.epub
└── 三体.pdf
```

平铺模式不接受嵌套读物目录，同名但不同格式的文件仍是不同作品。

### 卷册（VOLUMES）

固定结构为 `根目录/Work/Version/Volume.ext`：

```text
books/
└── 三体/
    ├── 中文版/
    │   ├── 01 地球往事.epub
    │   ├── 02 黑暗森林.epub
    │   └── 03 死神永生.epub
    └── 英文版/
        └── 01.epub
```

Work 与 Version 必须是目录，Volume 必须是 Version 目录下的直接文件；更深层嵌套不属于
此模式。

### 有声书（AUDIOBOOK）

根目录单个音频文件形成一个作品和卷册；作品目录中的直接音轨形成一个多音轨卷册；作品
目录下的每个卷目录形成一个卷册：

```text
audiobooks/
├── 魔戒.m4b
└── 某有声书/
    ├── 第一卷/
    │   ├── 001.mp3
    │   └── 002.mp3
    └── 第二卷/
        └── 001.mp3
```

同一作品目录不能同时包含直接音轨和卷目录。音轨与卷册都使用自然文件名顺序。

所有模式都读取原始文件，不生成派生出版物。上传文件必须先落到符合所选组织方式的位置，
再由定时或手动根目录扫描创建目录拓扑和导入任务；`LIBRARY_SCAN_INTERVAL_MS` 控制定时
扫描间隔。本阶段不处理文件消失、不可访问或用户重命名后的数据库对账，也不兼容旧数据库；
部署本次重构时应使用新的数据库基线。

## English

Each library has one independent root and one organization mode. The scanner interprets
only paths relative to that root. Directories and files define Work, Version, and Volume;
metadata never changes structure.

- `FLAT`: each supported file directly under the root is a separate Work with an implicit
  Version and one Volume. Nested publication paths are invalid.
- `VOLUMES`: the exact shape is `root/Work/Version/Volume.ext`; Work and Version are
  directories, and each Volume is a direct file under its Version.
- `AUDIOBOOK`: a root audio file is one Work/Volume; direct tracks under a Work form one
  multi-track Volume; each immediate child directory under a Work forms a separate Volume.
  Direct tracks and volume directories cannot be mixed in the same Work.

Volumes and tracks use natural filename ordering. Every mode reads the original file and
does not create a derived publication. Uploads must land at a valid path before the scanner
creates topology and import tasks. Periodic root scans use `LIBRARY_SCAN_INTERVAL_MS`, and
manual rescans submit the same bounded queue work. This phase does not reconcile vanished,
inaccessible, or user-renamed files, and it does not support old databases; deploy it with
the fresh schema baseline.
