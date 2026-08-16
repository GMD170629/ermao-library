# Work Detail visual issue ledger

Target contract: `target-contract.md` v3
Previous accepted build: physical-device baseline in `baseline/android/`

| ID | Severity | Baseline evidence | Target axis | Candidate hypothesis | Status |
|---|---|---|---|---|---|
| WD-01 | Major | Real one-volume audiobook: `baseline/android/work-detail/zh-CN-light-default/02-work-detail.png`; fixture multi-volume and single-EPUB captures | Hero identity alignment and first-scan hierarchy | Always top-align the identity copy with the 2:3 hero cover. The current data-dependent center/bottom alignment moves the title down when identity metadata is short and moves the cover down when identity metadata is long. | Open for candidate 01 |
| WD-02 | Minor | All three deterministic Work Detail fixture captures | Primary decision-path emphasis | Re-evaluate only after WD-01 is accepted. The filled action is already dominant; no width/style change is justified without a non-regressing physical candidate. | Deferred |
| WD-03 | Minor | `work-volumes-zh-CN-light.png` | First-fold density | Required tabs, media selector, and three-column grid are present. Re-evaluate vertical rhythm only after WD-01; do not remove required controls to imitate the directional reference. | Deferred |
| WD-04 | Major | User clarification on 2026-08-16; deterministic EBOOK fixture versus real audiobook-only baseline | Reading decision block | Use the deterministic EBOOK state as Primary and retain reading progress, shelf, and the truthful reading CTA directly after the hero. Treat the audiobook-only product screenshot as a data-dependent Flow state, not the visual target. | Fixed in contract; physical recapture pending |

## Candidate 01 promotion check

- Single structural hypothesis: top-align hero cover and identity copy for every normal-font data variant.
- Expected improvement: stable cover/title alignment in both the real short-metadata state and deterministic long-metadata state.
- Must remain unchanged: 2:3 cover size, title wrapping, tag/status/series order, progress, actions, conditional tabs, media control, three-column grid, chapters, shell and navigation.
- Reject if any retained axis becomes less legible, clipped, overlapped, or less dense than the physical baseline.
