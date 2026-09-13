# Ermao Books

English | [简体中文](README.md)

**Turn your book folders into a library you want to browse.**

Novels, comics, PDFs, audiobooks—give your collection a place to be enjoyed. Run Ermao Books on a NAS or home server to organize your personal or family library, read on your computer, continue on your phone, or settle in with an audiobook.

## Make time for your books

- **Find your next read.** Search by title, author, or tag. Organize collections with custom shelves, smart shelves, and reading statuses; fill in covers and book details.
- **Open a novel or comic.** Read EPUBs, PDFs, and comics in your browser, jump between chapters, and adjust the display and page-turning options.
- **Listen while you unwind.** Chapter navigation, playback speed, and a sleep timer make audiobooks a companion for chores or bedtime.
- **Pick up where you stopped.** Sync reading and listening progress across devices signed in to the same server. Use a desktop or mobile browser, or the Android app.
- **Read your way.** Configure email delivery to send EPUBs and PDFs to Kindle. Enable OPDS to browse and download books in compatible readers; third-party reading progress is not synced.

Common formats include EPUB, MOBI, AZW3, TXT, PDF, CBZ/CBR and ZIP/RAR comic archives, plus M4B, MP3, and FLAC audio. Import support does not guarantee playback on every device: audio is not transcoded and requires a compatible decoder. DRM-protected files are unsupported.

[Android APK / fnOS downloads](https://github.com/GMD170629/ermao-library/releases) · [fnOS guide](deploy/fnos/README.md). No iOS IPA is currently published.

## Install with Docker

Supports amd64 / arm64. Create `library` and `data/storage` folders in your deployment directory, then save this as `compose.yaml`:

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

Run `docker compose up -d` and open `http://your-server:3000`.

1. Follow setup to create an account, add `/libraries/books`, and choose its organization mode.
2. Place books in `library` using the [folder layout rules](docs/library-root-layout.md), then scan them into your library.
3. Choose a book to read or an audiobook to play.

For existing books, replace `./library` with their directory. The container uses UID/GID `1000:1000`; adjust `PUID`/`PGID` in `.env` if needed. This user needs read/write access to `data/storage` and read access to books, plus write access for uploads. Keep the data mount. See the [deployment guide](docs/library-root-layout.md#部署挂载) for more options.

## Guides and community

[Wiki](https://github.com/GMD170629/ermao-library/wiki) · [Docs](docs/README.md) · [Report an issue](https://github.com/GMD170629/ermao-library/issues) · QQ group: `154560969` · [MIT license](LICENSE)
