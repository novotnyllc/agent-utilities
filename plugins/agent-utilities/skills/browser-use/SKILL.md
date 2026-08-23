---
name: browser-use
description: "Control the user's existing signed-in Chrome: native browser tool first, with direct DevTools attachment only as a last fallback."
---

# Browser Use

Control the user's existing real Chrome profile, especially for login-dependent work and live UI verification.

Config repair details live in `mcporter-config.md`.

## Route

1. Use a native browser-control tool when it is callable in the active session.
   Installed on disk is not enough. In Codex, this is usually the `Chrome` or
   `Chrome [Internal]` plugin.
2. Use direct DevTools (CDP) attachment only as the explicit last fallback.

**The ordering is the point.** Direct CDP attachment exposes the full
real-profile tab set and can raise Chrome's blocking **Allow remote debugging?**
prompt, so it is what you fall back TO, never what you reach for first. A run
that opens with CDP has skipped the route, not taken it.

Never use isolated Chrome, the Codex in-app browser, Playwright, Puppeteer,
AppleScript, `osascript`, generic GUI scripting, or macOS `open` as a browser-control
substitute unless the user explicitly asks for an isolated or new browser.
Peekaboo is allowed only for Chrome or extension setup and visible prompts.
Login-heavy sites often depend on the real profile's cookies, SSO, device trust,
and extensions.

For a rendered-browser bug, prove behavior through this real profile. Treat
`curl`, source inspection, API checks, and isolated test browsers as supporting
evidence, not substitutes for live UI proof.

## Typical Flow

List pages, select only a shared target, snapshot before acting, and use fresh
snapshot UIDs. Prefer DOM snapshots over screenshots unless layout matters.

```bash
mcporter call chrome-devtools.list_pages --args '{}' --output text
mcporter call chrome-devtools.select_page --args '{"pageId":9}' --output text
mcporter call chrome-devtools.take_snapshot --args '{}' --output text
mcporter call chrome-devtools.click --args '{"uid":"1_38","includeSnapshot":true}' --output text
mcporter call chrome-devtools.fill --args '{"uid":"1_13","value":"text","includeSnapshot":true}' --output text
mcporter call chrome-devtools.evaluate_script --args '{"function":"() => document.title"}' --output json
```

For live UI proof, capture the current page state before the action, perform
the requested interaction, then snapshot or evaluate the rendered result.
Keep secrets out of DOM, input, network, console, and screenshot output. For
credential checks, return only safe shape such as present/absent, length,
status code, or account/organization label.

If automation is unavailable, report the verification gap instead of silently switching to prohibited or isolated tooling.

## Argument and Output Mechanics

`--args` accepts inline JSON only. It does not read `@file`. Flag-style named
arguments do:

```bash
mcporter call chrome-devtools.navigate_page url=@/tmp/target-url.txt --output text
mcporter call chrome-devtools.evaluate_script function=@/tmp/probe.js --output json
```

Treat this as a safety primitive, not just ergonomics. A sign-in URL, magic
link, or callback URL is credential-equivalent: write it to a mode-0600 file and
pass it by file reference so it never reaches shell history, process arguments,
or captured tool output. The same form carries a multi-line JavaScript function
without quoting or control-character errors.

Other call mechanics worth knowing before a login flow:

- The default call timeout is short (about five seconds). Real navigation,
  snapshots, and consent pages routinely exceed it, and the failure looks
  identical to a hung page. Pass `--timeout 30000` for anything interactive.
- `take_screenshot` with `filePath` is confined to the server's configured
  workspace roots and refuses arbitrary paths. Omit `filePath`, read the
  base64 image from `--output json`, and decode it locally.
- `new_page` can fail with a restricted/unavailable tab when the target is not
  shared. Navigate an already-shared tab instead of creating one.
- `mcporter list <server> --schema` prints the real function signatures. Use it
  rather than guessing parameter names.

## Clicks That Do Not Click

A `click` by `uid` can return success and still do nothing: some pages bind
their handlers so that a synthetic click is ignored. Silence is not proof of
action, so verify state after every activation rather than assuming it worked.

When a click no-ops, drive the control from the keyboard with `press_key`
(`Tab`, `Shift+Tab`, `Enter`) and confirm focus with a screenshot before
committing. Focus rings are the only reliable evidence of which control is
about to receive `Enter`, and consent screens routinely put the safe-looking
prominent button next to a low-emphasis link that is the one you actually want.
Blind `Enter` on such a page picks the wrong control.

Snapshot `uid` values are invalidated by any navigation or re-render. Re-run
`take_snapshot` and re-resolve the `uid` after every step; a stale `uid`
reports that the element no longer exists, which is a cue to re-snapshot rather
than to retry the same call.

## Fallback: Full-Profile Direct Attachment (CDP)

Use this only after a callable native browser tool has been ruled out — not
merely "not tried". It exposes the full real-profile tab set and can show
Chrome's blocking **Allow remote debugging?** prompt, which is exactly why it
is last.

When a visible, unambiguous Chrome prompt asks to allow the attachment, approve
it once, then rerun `list_pages`. If the prompt is absent, ambiguous, or the
retry fails, stop and ask the user or report that Chrome DevTools MCP is
unavailable. Do not loop approvals, repeatedly restart Chrome or mcporter, or
kill browser processes.

Verify that `list_pages` shows the intended real-profile tabs before acting, and
label this path as full-profile direct attachment so a reader can tell which
route actually ran.
