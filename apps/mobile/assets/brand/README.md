# Mobile brand assets

These files are deterministic derivatives of the approved master artwork:

- Source: `apps/web/public/brand/ermao-library-app-icon-v1.png`
- Source SHA-256: `8ee00fd96c3fc70c4e68d75a6d292e640675d1fd90162a2abdca6048b03349fb`
- Source dimensions: 1024 × 1024 px

`ios-app-icon.png` and `android-legacy-icon.png` preserve the opaque,
square master without adding rounded corners. Android adaptive assets keep
the circular cat mark within the central safe area, use the Mobile warm
background token, and provide a single-alpha monochrome form for themed
icons.

The native launch screen is intentionally background-only: `app.json`
configures the light and dark Mobile background tokens through
`expo-splash-screen`. This keeps launch continuity with connection, sign-in,
and library entry screens without turning startup into a logo advertisement.

Regenerate platform derivatives from the approved master only. Do not derive
new assets from these outputs, redraw the cat, apply AI restyling, recolor the
mark, or import the Web asset at Mobile runtime.
