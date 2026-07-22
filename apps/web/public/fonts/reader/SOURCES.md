# Reader Font Sources

These files are open-source webfont assets used by the EPUB reader. Proprietary system fonts such as PingFang SC and Microsoft YaHei are not redistributed here.

| Reader option | Local file | Bundled font | Source | License |
| --- | --- | --- | --- | --- |
| 苹方 | `sans.woff2`（共享回退） | Source Han Sans SC VF | https://github.com/adobe-fonts/source-han-sans | SIL Open Font License 1.1 |
| 黑体 | `sans.woff2`（共享回退） | Source Han Sans SC VF | https://github.com/adobe-fonts/source-han-sans | SIL Open Font License 1.1 |
| 宋体 | `songti.woff2` | Source Han Serif SC VF | https://github.com/adobe-fonts/source-han-serif | SIL Open Font License 1.1 |
| 微软雅黑 | `sans.woff2`（共享回退） | Source Han Sans SC VF | https://github.com/adobe-fonts/source-han-sans | SIL Open Font License 1.1 |
| 楷体 | `kaiti.woff2` | LXGW WenKai subset | https://gitee.com/airinghost/lxgw-wenkai-subset | SIL Open Font License 1.1 |

苹方、黑体和微软雅黑优先使用设备系统字体；缺失时共同回退到唯一的 `sans.woff2`，避免重复打包同一份字体。
