# Mobile Design QA evidence index

Work Detail evidence captured before 2026-08-26 is retained only as deprecated historical evidence. It must not be used as an implementation target or acceptance baseline. This includes:

- `screenshots/**/work-about-*`, `work-actions-*`, `work-single-ebook-*`, and `work-volumes-*`;
- `screenshots/ios-work-detail-physical-zh.png`;
- `content-discovery-polish/work-detail-before-and-reference.png`;
- `android-warm-page-v2/runs/20260815-work-detail-v4/`;
- `visual-runs/20260816-work-detail-control-menu-v1/` and `visual-runs/20260816-work-detail-control-menu-v2/`;
- `visual-runs/20260816-work-detail-refinement-v1/` and `visual-runs/20260816-work-detail-v6/`.

Current Work Detail behavior comes only from the latest Web implementation in `apps/web/features/books/book-detail-page.tsx`, `apps/web/features/books/ui/book-content-browser.tsx`, and `apps/web/features/books/ui/resource-detail-view.tsx`. New mobile evidence must exercise the shared single-resource detail and multi-resource content-browser behavior, implicit original-file download before opening every reflowable publication, streamed PDF/comic delivery, the independent explicit Download Center surface, and the continuous cover-background fade. Audio continues through its player and must not enter the Reader download transition.
