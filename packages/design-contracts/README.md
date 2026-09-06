# Cross-platform visual contract

`visual-tokens.json` is the sole numeric owner for shared Web, Android, and iOS visual semantics.
It defines the light-only application shell, five independent Reader themes, spacing, radii,
typography roles, stable component metrics, and platform minimum touch targets.

Platform adapters may map these values to CSS pixels, Compose dp/sp, SwiftUI points, Material,
Readium, or native controls. Safe areas, breakpoints, animation timing, system menu/sheet geometry,
and Reader setting behavior do not belong in this contract.

Version 1.2.0 aligns App actions with the approved Web mobile orange: `actionAccent`
and `brandAccent` are both `#FF4F2A`, with `onAction` on filled primary actions.
Page canvases use `canvas`, navigation surfaces use `navigation`, text inputs use
`surface`, popup surfaces use `surfaceRaised`, and selections use `accentSoft`
with `brandAccent` content. App action/selection colors are not contrast-threshold
acceptance gates; independent Reader palette validation remains unchanged.

From `apps/mobile`, run:

```text
./gradlew generateDesignTokens
./gradlew syncWebDesignTokens
./gradlew verifyDesignTokens
```

Kotlin, Swift, and Android XML remain build outputs. The Web CSS and TypeScript files are committed
because Web builds are Node-only; they must be updated only with `syncWebDesignTokens`.
