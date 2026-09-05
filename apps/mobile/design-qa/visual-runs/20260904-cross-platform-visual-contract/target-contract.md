# Cross-platform visual contract target

## Locked outcome

- The Web mobile palette is the semantic source for Web, Android, and iOS.
- The application shell is always light, including when the operating system uses dark appearance.
- Reader exposes Day, Warm, Green, Night, Black, and System. System resolves to Day in light appearance and Night in dark appearance.
- Reader content, controls, links, and surrounding surfaces use the same generated theme palette; authored publication backgrounds must not defeat the active Reader theme.
- Native navigation, menus, sheets, safe areas, and platform font scaling remain native.
- This phase migrates central themes and Reader palettes only; page-level hardcoded styling is explicitly outside scope.

## Acceptance evidence

- Deterministic contract generation and tracked Web drift verification pass.
- Web lint, typecheck, focused Reader tests, and production build pass.
- Android unit tests, AndroidTest compilation, debug APK assembly, cold launch, app-shell light/dark checks, five manual Reader themes, and System Day/Night checks pass on a physical device.
- iOS generated-token mapping and tests are present, but simulator build/tests and physical-device screenshots are required before the overall visual verdict can become `PASS`.
