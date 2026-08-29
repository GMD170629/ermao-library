# Reader Font Sources

These files are open-source webfont assets used by the EPUB reader. Proprietary system fonts such as PingFang SC and Microsoft YaHei are not redistributed here.

| Reader option | Local file | Bundled font | Source | License |
| --- | --- | --- | --- | --- |
| 苹方 | `sans.woff2` | Source Han Sans SC VF | https://github.com/adobe-fonts/source-han-sans | SIL Open Font License 1.1 |
| 宋体 | `songti.woff2` | Source Han Serif SC VF | https://github.com/adobe-fonts/source-han-serif | SIL Open Font License 1.1 |
| 楷体 | `kaiti.woff2` | LXGW WenKai subset | https://gitee.com/airinghost/lxgw-wenkai-subset | SIL Open Font License 1.1 |

苹方优先使用设备系统字体；缺失时回退到 `sans.woff2`。宋体和楷体分别使用其对应的内置字体文件。

`android-legacy/` contains weight-400 static WOFF2 builds of the same licensed
fonts. Android packages these three files because older system WebViews cannot
decode the CFF2 variable WOFF2 files used by current Web and iOS readers.
