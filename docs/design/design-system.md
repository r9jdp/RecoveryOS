# RecoveryOS design system

Status: Phase 5 submission candidate

Audit baseline: 2026-08-27

## Intent

RecoveryOS is an original merchant operations product. Its interface borrows the public Razorpay site's visual rhythm—precise blue actions, dark navigation, pale utility surfaces, compact radii, and clear typographic contrast—without copying Razorpay's identity, logo, illustrations, layout, or proprietary assets.

The identity mark is a RecoveryOS-owned abstract recovery glyph. `Razorpay Test Mode` is displayed only as an integration-status badge and does not imply partnership or endorsement.

## Foundations

The canonical variables live in `apps/web/src/styles/tokens.css`. Components consume them through `recovery-ui.module.css`.

| Role           | Token                               | Value                         |
| -------------- | ----------------------------------- | ----------------------------- |
| Primary action | `--ros-brand`                       | `#305EFF`                     |
| Link           | `--ros-link`                        | `#2950DA`                     |
| Primary text   | `--ros-ink`                         | `#192839`                     |
| Heading text   | `--ros-ink-secondary`               | `#132644`                     |
| Muted text     | `--ros-text-muted`                  | `#40566D`                     |
| Canvas         | `--ros-canvas`                      | `#FFFFFF`                     |
| Soft surfaces  | `--ros-surface-subtle/muted/strong` | `#F8FAFC / #F1F5FA / #F0F4F6` |
| Border         | `--ros-border`                      | `#DFE3E9`                     |
| Success        | `--ros-success`                     | `#009E5C`                     |
| Danger         | `--ros-danger`                      | `#D52B1E`                     |
| Navigation     | `--ros-dark`                        | `#032A3E`                     |
| Brand tint     | `--ros-brand-soft`                  | `#D0E0FF`                     |

Spacing follows a four-pixel base grid. Standard radii are 4, 8, 12, and 16 pixels. Primary controls are 48 pixels tall, and touch-critical large actions are 56 pixels tall.

### Typography

- Display headings: TASA Orbiter Display, 750 target weight, tight tracking.
- Product UI and body: Inter, 450–750 target weights.
- System fallbacks remain mandatory and have been tuned to preserve layout.
- Font binaries are not redistributed. See `apps/web/public/fonts/README.md` for the licensed self-hosting procedure.

## Component inventory

The UI package is intentionally dependency-free and compatible with Next.js App Router:

- `Button`: primary, secondary, ghost, and danger treatments; three sizes; loading state.
- `Input` and `Select`: labels, required/optional state, hints, inline errors, and accessible descriptions.
- `Badge` and `TestModeBadge`: evidence, status, safety, and provider environment labels.
- `Card` and `MetricCard`: operational groupings and dashboard KPI values.
- `Table`: semantic, horizontally scrollable data tables.
- `Drawer`: modal semantics, focus containment, Escape/backdrop close, scroll locking, and focus restoration.
- `Timeline`: provider events, decisions, and evidence with semantic ordered-list markup.
- `ChartShell` and `BarChart`: chart framing plus a dependency-free accessible preview chart.
- `Navigation`, `Brand`, `AppShell`, and `PageHeader`: responsive merchant workspace structure.
- `Alert`, `Skeleton`, and `EmptyState`: complete feedback and loading coverage.

Import components from the owned package barrels:

```tsx
import { AppShell, PageHeader } from "@/components/layout";
import { Badge, Button, Card, CardBody } from "@/components/ui";
```

The review surface is `/design-system`. It intentionally uses real merchant-product vocabulary so
content density and status color can be assessed in context. Product routes now use the same
primitives across the Control Tower, case workspace, approvals, settings, RecoveryBench, voice, and
A2A exact-scope approval.

## Product usage rules

1. Reserve brand blue for the primary action, selected navigation, and high-value links.
2. Use success only for authoritative confirmation. A client callback or optimistic UI state is never shown as verified recovery.
3. Use danger for destructive actions and confirmed failure, not routine warnings.
4. Pair status colors with text. Never use color as the only signal.
5. Use no more than one primary action in a card or drawer footer.
6. Monetary metrics must state whether they are simulated, test verified, or production verified.
7. Keep payment-provider surfaces and RecoveryOS controls visually distinct.
8. Do not use the Razorpay logo, proprietary illustrations, copied screenshots, or language suggesting affiliation.

## Responsive behavior

- At 1200px and above, dashboards can use four KPI columns.
- Below 1200px, four- and three-column regions collapse to two columns.
- Below 832px, the desktop sidebar gives way to the mobile header and single-column feature regions.
- Below 608px, all metric grids and paired form fields collapse to one column, and drawers become full width.
- Data tables remain semantic tables and scroll inside their own labelled viewport; columns are not silently removed.

The application shell now provides responsive mobile navigation with current-route state. Tables
retain their labelled horizontal scroll regions rather than dropping financial or evidence columns.

## Accessibility

- All interactive elements have a visible focus indicator with at least a three-pixel brand-tint ring.
- Body text and component states target WCAG 2.2 AA contrast on their defined surfaces.
- The drawer has `role="dialog"`, `aria-modal`, labelled title/description, keyboard trapping, focus restoration, and Escape support.
- Alerts use status or alert live-region roles according to severity.
- Charts expose a textual value summary; production charts must add equivalent table or summary access.
- Skeletons are hidden from assistive technology; their parent declares the loading state.
- Motion durations collapse when `prefers-reduced-motion: reduce` is active.
- Forced-colors mode restores explicit system borders.

## Verified implementation notes

- Navigation uses route-aware links and the data layer consumes the frozen OpenAPI declaration where
  the live API is available, with an explicit labelled fixture fallback.
- Drawer focus containment/restoration, keyboard-only approval, semantic control labels, landmarks,
  duplicate-ID checks, and desktop/mobile overflow checks are automated.
- Six frozen Phase 4 baselines cover Control Tower, case workspace, and voice safety at 1440×960 and
  390×844. The native scanner is a targeted structural/keyboard check, not a complete WCAG audit.
- The public demo remains mock-only when provider credentials are absent. Evidence badges must use
  `SIMULATED` or a genuinely established provider-verification class.
