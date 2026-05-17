# DESIGN

## Direction

TaxOps Control Desk uses a premium, simple, and highly legible desktop operations style.

Reference library:

```text
C:\Users\LIN\.codex\references\awesome-design-md\design-md
```

Primary references:

- `apple`: calm premium spacing, restraint, clarity.
- `tesla`: high-contrast luxury, minimal visual noise.
- `linear.app`: dense but readable operational interface.
- `stripe`: clear form hierarchy, data-entry trust, polished details.

These are references only. Do not copy brand names, logos, trademarked assets, or proprietary identity.

## Product Fit

This is not a marketing landing page. It is a desktop workbench for Taiwan accounting and tax office operations.

The UI should feel:

- Quiet.
- Precise.
- Premium.
- Trustworthy.
- Operational.
- Easy to scan.

The UI should not feel:

- Flashy.
- Decorative.
- Consumer-social.
- Dashboard-theater.
- Overly dark or gamer-like.
- Like a web SaaS landing page.

## Visual Rules

- Use restrained neutral surfaces.
- Use a small number of accent colors.
- Use accent color only for priority, selection, and key actions.
- Do not rely on color alone for state.
- Prefer text + subtle visual treatment for status.
- Keep cards minimal and functional.
- Avoid nested cards.
- Avoid decorative gradient blobs, orbs, bokeh, or ornamental backgrounds.
- Keep border radius modest, typically 6px to 8px.
- Use clear separators and spacing instead of heavy borders.

## Typography

- UI language: Traditional Chinese.
- General text minimum: 14px.
- Table text minimum: 13px.
- Page title: around 20px.
- Section title: around 16px.
- Error text minimum: 14px.
- Do not use tiny text to force density.
- Do not use negative letter spacing.

## Layout

- Prioritize clarity over visual drama.
- Navigation is stable on the left.
- Main content is dense but not cramped.
- Forms use left labels and right inputs.
- Long forms use scrolling content with visible bottom actions.
- Tables support scanning, filtering, sorting, pagination, and tooltips.
- Path fields must preserve buttons and show full path tooltip.
- No enabled UI element may be hidden, clipped, or overlapped at 1366 x 768.

## Components

Buttons:

- Use Traditional Chinese labels.
- Primary button is visually clear but not loud.
- Dangerous actions require confirmation.
- Unimplemented actions are disabled and show `此功能尚未開放`.

Tables:

- Chinese column labels only.
- Long text elides with tooltip.
- Customer and engagement names may stretch.
- Status and date columns use stable widths.
- Empty state must explain the next action.

Forms:

- Group fields by business meaning.
- Show validation errors near fields.
- Do not clear user input after validation failure.
- Cursor should move to first invalid field.

Dialogs:

- Keep dialogs within screen bounds.
- Use concrete confirmation text.
- Do not show raw exceptions.

## Status Language

Never show raw enum values in UI.

Examples:

- `todo` -> `待處理`
- `doing` -> `處理中`
- `waiting_client` -> `等客戶回覆`
- `waiting_internal_review` -> `等內部覆核`
- `done` -> `已完成`
- `cancelled` -> `已取消`
- `needs_manual_review` -> `需人工確認`

Unknown status display:

```text
未知狀態，請聯絡系統管理員
```

The unknown status must also be written to system log.

## Design Acceptance

The UI design is acceptable only if:

- It is clear to non-engineering accounting office users.
- It does not expose database fields, API names, enum values, or raw exceptions.
- It works at Windows scaling 100%, 125%, and 150%.
- It works at 1366 x 768 and 1920 x 1080.
- It has no fake enabled actions.
- It keeps the premium-simple style while preserving operational density.
