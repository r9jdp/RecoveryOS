# RecoveryOS font assets

RecoveryOS uses the following font stacks:

- Display: `TASA Orbiter Display`, falling back to Inter, Avenir Next, and Segoe UI.
- Interface/body: `Inter`, falling back to Segoe UI, Roboto, Helvetica, and Arial.

No font binaries are committed here. TASA Orbiter Display and some Inter distributions may have license or redistribution conditions that must be checked by the project owner.

To install approved self-hosted assets:

1. Obtain the font files from an authorized source and confirm web-embedding rights.
2. Put only the licensed `.woff2` files in this directory.
3. Add `@font-face` declarations to `src/styles/tokens.css` using `font-display: swap`.
4. Preload only the heading and body weights used above the fold from the application layout.
5. Keep the existing fallback stacks so text remains visible while fonts load.

The design system intentionally works without these binaries. Do not copy font files from Razorpay's website or another third-party deployment.
