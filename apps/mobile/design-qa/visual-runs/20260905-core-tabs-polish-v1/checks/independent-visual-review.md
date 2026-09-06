# Independent visual review — core tabs polish v1

Review scope: original final captures in `core-tabs-polish-v1/final`, reviewed at the approved physical-device target (portrait, 1440 × 3200, density 3.5, zh-CN). Screenshots were inspected visually first; XML was used only to confirm selected bounds. No device, browser, build, or production code was touched.

## Result

No actionable visual defect was found in the requested final captures. The fixed target is visually met for the reviewed surfaces. The primary acceptance decision remains with the main reviewer.

## Checks by target

- **Four-tab shell and system insets — pass.** `17-home-stable.png`, `04-library-stable.png`, `19-shelves.png`, and `20-me.png` show the first, middle, and last selected navigation states with the same four destinations and balanced selected capsules. `12-directory.png`, `18-resource.png`, and `37-nested-resource.png` preserve the owning tab state. The top system inset is clear of page titles and compact bars.
- **Library shell and grid — pass.** `04-library-stable.png` preserves search → scope → count → three-column covers; titles wrap to two lines and the empty-author case does not leave an empty author row. The search control has the shared rounded treatment and leading text alignment.
- **Library menus and sort states — pass.** `05-library-menu.png`, `06-library-sort.png`, and `09-library-sort-middle.png` retain the native popup shape. XML bounds corroborate 168 physical-pixel (48dp) item rows at density 3.5, reserved icon/check space, and unchanged label start positions across selected states. First and middle selections are visibly represented.
- **Directory root and child visibility — pass.** `12-directory.png` shows the 96dp × 144dp root cover and distinguishable child titles in the initial viewport. `13-directory-menu.png` retains the directory action popup. `15-directory-sort.png` keeps the sort popup as a separate popup role, and `16-directory-list.png` preserves list mode with readable child titles and source captions.
- **Directory content grid and actions — pass.** `35-directory-contents.png` allows multi-line grid titles through three lines and keeps the `EPUB` format caption on its own row. `36-directory-actions.png` has the real directory action popup: the download icon is present, all other labels share the same text axis, and the disabled regenerate action is visibly disabled. The long path/title content is data-dependent and was not treated as a layout defect.
- **Home multi-item branch — pass.** `17-home-stable.png` keeps Continue reading → Recent reading → Recent additions, with two recent-reading items in the horizontal branch. The current data count is accepted as captured and is not treated as a regression.
- **Resource details — pass.** `18-resource.png` retains the 120dp resource hero, primary reading action, secondary action row, and only available metadata rows. `37-nested-resource.png` makes the real child title readable on the first screen and preserves the three available secondary actions.
- **Shelves and Me — pass.** `19-shelves.png` preserves search, tabs, shelf row, trailing affordance, and the data-dependent empty remainder. `20-me.png` preserves section order, row gutters, text axes, and trailing slots. No account or server value is copied into this review.
- **Password states — pass.** `22-password-empty.png`, `23-password-focused.png`, and `24-password-visible.png` show the shared 12dp control treatment, leading-aligned field text, stable password action slots, focused label/outline/cursor, and visible/hidden text behavior.
- **Kindle and SMTP — pass.** `26-kindle.png` shows the empty sender summary as `未设置`. `29-smtp.png` keeps the connection → sender identity → delivery limits order with leading-aligned numeric and text fields. `30-encryption-first.png`, `31-encryption-last.png`, and `32-encryption-middle.png` cover first/last/middle encryption selections with symmetric segmented geometry; `33-smtp-bottom.png` preserves the lower fields and test action while scrolled.

## Geometry spot checks

- Directory root cover in `12-directory.xml`: `[552,417][888,921]` = 336 × 504 physical px = 96 × 144dp.
- Resource hero covers in `18-resource.xml` and `37-nested-resource.xml`: `[510,417][930,1047]` = 420 × 630 physical px = 120 × 180dp.
- Library popup in `05-library-menu.xml`: `[992,333][1426,1010]`; menu rows are 168 physical px = 48dp.
- Directory action popup in `36-directory-actions.xml`: `[446,333][1426,1346]`; action rows are 168 physical px = 48dp and labels share the x=614 text axis.
- Password and SMTP controls use the same `[56,…][1384,…]` outer bounds with leading content around x=112, matching the reviewed visual alignment.

## Exclusions honored

No contrast, large-font, TalkBack, rotation, or other excluded matrix was assessed. Floating menus, sheets, tabs, and segmented controls were reviewed in their existing distinct forms. Repeated or data-dependent covers were not treated as loading defects or replacement requests.
