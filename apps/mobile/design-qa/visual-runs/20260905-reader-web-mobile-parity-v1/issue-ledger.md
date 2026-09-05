# Reader Web mobile parity issue ledger

| ID | Severity | Root cause | Acceptance condition | Status |
|---|---|---|---|---|
| VIS-001 | major | Android Reader uses independent Material modal sheets instead of the Web integrated floating console. | All four panels share the floating surface, retain navigation, hide progress, and match target geometry on the physical device. | resolved in iteration-09 |
| VIS-002 | major | Android Reader renders platform-specific setting rows and generic availability text. | Both platforms render generated catalog order, state, and localized reason with matching compact component proportions. | resolved in iteration-09 |
| VIS-003 | major | Web EPUB parsing omits NCX and can publish an empty TOC. | EPUB3, NCX, and reading-order paths produce safe, navigable, hierarchical entries with regression tests. | resolved in iteration-04 Web target |
| VIS-004 | minor | Android Notes segmented control has no state transition. | Bookmark and annotation tabs switch and expose their truthful content states. | resolved; 15 focused device tests pass |
| VIS-005 | major | Final same-state physical-device evidence is not yet captured. | Primary, Flow, Format, and Risk evidence plus implementer and independent clean reviews pass on the unchanged final build. | resolved in iteration-11; independent review PASS |
