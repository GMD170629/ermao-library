# Mobile Figma implementation ledger

This ledger records the live design evidence used for production Mobile page
implementation. It complements, and does not replace,
`docs/mobile-app-design-guidelines.md`.

## 2026-08-09 · Home and Bookshelf

- Figma file: `IPdikyDhzAGJ60hdbsywgs`
- Home source: `02 · Home`, node `16:1578`
- Bookshelf source: approved `05 · Bookshelf`, node `31:4`
- Shared components source: node `31:3`
- Implementation scope: `apps/mobile`

The required `get_design_context` request was attempted first and was rejected
by the Figma Starter MCP call limit. The same live file and exact nodes were then
inspected in the authenticated Figma UI. No Reference Only frame was used as a
production visual source.

### Verified page states

- Home: Default Light, Empty Light, Default Dark
- Bookshelf: Grid Light, List Light, Grid Dark, List Dark
- Baseline device frame: 393 × 852 pt
- Compact page margin/content width: 20 pt / 353 pt
- Layout grid: 4 pt
- Minimum interactive target: 44 pt
- Search and standard controls: 48 pt

### Verified Home hierarchy

- Large “首页” title with dynamic book/unread summary; empty subtitle becomes
  “从一本书开始”.
- Circular appearance control in the header.
- Search control, continue-reading card, and a three-cover recent-books row.
- Empty state uses the approved book illustration treatment and one primary
  “import first book” action.
- Bottom navigation remains visible with labels for Home, Bookshelf, and Me.

### Verified Bookshelf hierarchy

- Header add action and the approved grid/list view switcher.
- Separate Collection and Bookshelf sections.
- Shared `Shelf Visual` variants: Collection, Tile, and Rail in light/dark.
- Bottom navigation uses the approved Home/Shelf/Mine active variants.

### Shared component names verified in Figma

- `Icon Button / Plus / Light|Dark`
- `View Switcher / Grid|List Active / Light|Dark`
- `Shelf Visual / Collection|Tile|Rail / Light|Dark`
- `Primary Tab Bar / Home|Shelf|Mine Active / Light|Dark`

The approved semantic colors, spacing, radii, typography, safe-area behavior,
large-text adaptation, and reduced-motion rules remain owned by
`docs/mobile-app-design-guidelines.md` and the shared Mobile theme. The composed
All Books and Me pages have no approved full-page frame; they use only those
approved foundations and shared components.
