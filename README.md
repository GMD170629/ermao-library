# 二毛图书（Ermao Books）

[English](README.en.md) | 简体中文

**把硬盘里的藏书，变成随手可读的私人图书馆。**

小说、漫画、PDF、有声书，收藏得多了，也需要一个方便找书、翻阅的地方。二毛图书部署在 NAS 或家庭服务器上，帮你整理个人与家庭藏书，在电脑上读书，在手机上继续，也能戴上耳机听一会儿。

## 让藏书读起来

- **找到下一本想读的书**：按书名、作者或标签查找，用自定义书架、智能书架和阅读状态整理收藏，补全封面与图书信息。
- **小说、漫画，打开就读**：在浏览器里阅读 EPUB、PDF 和漫画，按目录跳转，调整显示与翻页方式。
- **做家务时听，睡前也能听**：有声书支持章节切换、倍速和睡眠定时，长篇故事可以慢慢听完。
- **换个设备，接着上次读**：登录同一服务器，同步阅读与收听进度；电脑和手机都能通过浏览器访问，也有 Android 客户端。
- **用喜欢的阅读器看书**：配置邮件后发送 EPUB、PDF 到 Kindle；启用 OPDS 后，兼容阅读器可浏览和下载藏书（不同步第三方阅读进度）。

常见格式：电子书 EPUB、MOBI、AZW3、TXT 等，PDF，漫画 CBZ/CBR、ZIP/RAR 图片包，有声书 M4B、MP3、FLAC 等。导入支持不等于每台设备都能播放；音频不转码，播放取决于设备解码能力，不支持带 DRM 的文件。

[下载 Android APK / fnOS 安装包](https://github.com/GMD170629/ermao-library/releases) · [fnOS 说明](deploy/fnos/README.md)。iOS 暂无 IPA 发布包。

## Docker 安装

支持 amd64 / arm64。在准备部署的目录中创建 `library` 和 `data/storage` 文件夹，将以下内容保存为 `compose.yaml`：

```yaml
services:
  web:
    image: gamersgu/shuku-starship-web:prod
    restart: unless-stopped
    user: "${PUID:-1000}:${PGID:-1000}"
    environment:
      STORAGE_ROOT: /app/storage
      PORT: 3000
      HOSTNAME: 0.0.0.0
    ports:
      - "3000:3000"
    volumes:
      - ./data/storage:/app/storage
      - ./library:/libraries/books
```

运行 `docker compose up -d`，打开 `http://服务器地址:3000`。

1. 按页面向导创建账户，添加 `/libraries/books` 为书库，选择对应组织方式。
2. 将读物放入 `library`，按[目录规则](docs/library-root-layout.md)组织，完成扫描后进入书库。
3. 选一本书开始阅读，或播放一本有声书。

已有藏书可将 `./library` 换成实际目录。容器用户默认 UID/GID 为 `1000:1000`，可通过 `.env` 的 `PUID`/`PGID` 调整；需能读写 `data/storage`、读取书库，上传时还需书库写权限。保留数据目录挂载。更多配置见[部署说明](docs/library-root-layout.md#部署挂载)。

## 文档与交流

[使用 Wiki](https://github.com/GMD170629/ermao-library/wiki) · [项目文档](docs/README.md) · [问题反馈](https://github.com/GMD170629/ermao-library/issues) · QQ 群：`154560969` · [MIT 许可证](LICENSE)
