---
name: remote-mac
description: "Remote Mac operations: Tailscale, SSH, tmux, GUI fallback, safe checks."
---

# Remote Mac

Use when the user asks to run, inspect, repair, or automate something on another Mac.

## Configuration

Do not assume host names, users, repo paths, or service names. Discover them from the current machine and user-provided context.

Preferred sources, in order:

1. The explicit host/user/path in the user's request.
2. SSH config aliases: `ssh -G <alias>` and `~/.ssh/config`.
3. Tailscale state: `tailscale status --json` or `tailscale status`.
4. Optional local inventory: `${AGENT_UTILITIES_REMOTE_MAC_CONFIG:-$HOME/.config/agent-utilities/remote-macs.yaml}`.
5. LAN discovery only when needed: `dns-sd -B _ssh._tcp local` and `arp -a`.

The optional inventory file is user-owned. Treat it as hints, not proof:

```yaml
hosts:
  laptop:
    ssh: laptop.local
    tailscale: laptop
    user: claire
    notes: daily driver
```

## Discovery

1. Identify the intended host from the request or inventory.
2. Run `tailscale status` when Tailscale is likely involved.
3. If Tailscale is unavailable or SSH times out, try mDNS names such as `HOST.local`.
4. Verify host identity before making changes:
   - `hostname`
   - `whoami`
   - `sw_vers`
   - `pwd`

## SSH Rules

Use non-interactive SSH by default:

```bash
ssh -o RequestTTY=no -o RemoteCommand=none HOST 'COMMAND'
```

If an SSH alias auto-attaches tmux or runs a remote command, override it for one-shot checks:

```bash
ssh -o RequestTTY=no -o RemoteCommand=none ALIAS 'hostname; whoami'
```

Use login shells when checking developer tools installed through Homebrew or shell startup files:

```bash
ssh -o RequestTTY=no -o RemoteCommand=none HOST 'zsh -lc "command -v brew; command -v pnpm; command -v node"'
```

For long-running or interactive remote work, create a remote tmux session with a clear name and report the attach command.

## GUI Fallback

Prefer SSH and service APIs. Use GUI automation only when the task is explicitly GUI-bound or a security prompt blocks command-line completion.

Safe GUI fallback order:

1. Ask the user which remote desktop/session is visible.
2. Capture a screenshot/window list before clicking.
3. Use stable visible labels or coordinates derived from the latest screenshot.
4. Re-read state after each action.

Do not type or expose secrets into chat. If a keychain or browser prompt appears, describe the prompt and ask the user to approve or enter the secret.

## Service Checks

For any named service on the remote Mac:

1. Prefer repo docs, `AGENTS.md`, launchd plist labels, or process names from the user's request.
2. Read-only checks first:
   - `launchctl list | rg '<service-or-prefix>'`
   - `tmux list-sessions`
   - `ps axww | rg '<process>'`
   - `lsof -nP -iTCP:<port> -sTCP:LISTEN`
3. Do not install, start, stop, restart, unload, or edit services unless the user asks for that action.

## Safety

- Do not assume host identity from a stale IP.
- Do not print secrets from remote files, shells, keychains, env vars, or command output.
- Name every host and command path before destructive or state-changing work.
- If a host is unavailable after Tailscale plus LAN fallback, report exactly what was tried.
