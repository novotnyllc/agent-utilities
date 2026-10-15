# Prompt pack

Fill the `[brackets]`. The prompts are adapted from "How to Turn Opus 5.5 Into a
Reverse Engineer" (N01ennn, Oct 2026) and the REA docs.

## Setup (once per machine; skip if `mcp__rea__*` tools already exist)

```
Install REA and connect it to this coding agent using npx rea-agents@latest setup. Show me the setup plan for approval, then verify the installation.
```

Check: `npx -y rea-agents@latest doctor --client claude_code --json`
Native binaries also need Ghidra 12.1.x + JDK 21 (`doctor --provider ghidra --json`), or Hopper/IDA.

## Warm-up (optional, safe practice target)

```
Download https://rea.tools/examples/notes-example.zip into a new example folder and unpack it. Use REA to find what happens when I click Export notes.
```
```
Show where notes.csv is written, which fields it contains, and the relevant files and lines.
```

## Room A: the reader (cwd: reader/)

```
Use REA to investigate how [feature] works in [app]. Tag every claim as observation, inference or unknown, and cite the evidence.

Then write SPEC.md from the clean-room-rebuild SPEC template: behaviour, inputs, outputs, edge cases, at least [ten] worked examples, and open unknowns. Describe what it does. No code, no addresses, no names or assets from the original. Add every original symbol, string or name you saw to ../wall/denylist.txt.
```

Worked example (Windows Calculator %):
```
Use REA to inspect Windows Calculator's % button. Recover the rules after +, −, × and ÷. Write SPEC.md with the rules, ten worked examples and the edge cases (0%, 100%, negative numbers, % with no previous number). No code.
```

Electron apps keep code in `app.asar`:
mac `/Applications/<App>.app/Contents/Resources/app.asar`,
Windows `%LOCALAPPDATA%\Programs\<App>\resources\app.asar`,
Linux often `/opt/<App>/resources/app.asar`.

## The wall

```
bash <skill-dir>/scripts/cross-wall.sh [root]
```

## Room B: the builder (fresh session, cwd: builder/)

```
Build [feature] from SPEC.md in ./src. You have only SPEC.md: do not look outside this folder and do not use REA. Write tests from the behaviour and worked examples in the spec, and run them. Where SPEC.md lists an unknown, do not guess silently: pick the simplest behaviour, mark it in NOTES.md, and add a test that pins it.
```

## The oracle check (Room B)

```
Add three deliberately wrong variants of the implementation as patches in ./oracle/mutants/: constant.patch (change one constant), branch.patch (swap one branch), boundary.patch (shift one boundary by one). Run bash <skill-dir>/scripts/check-oracle.sh . "[test command]" and confirm all three are rejected. If any passes, fix the tests first.
```

## The goal (Room B)

```
/goal every case in SPEC.md passes in ./src, check-oracle.sh prints "ORACLE OK: 3/3 mutants rejected", and no file outside this folder was changed. or stop after 25 turns.
```

The `/goal` checker reads what the session prints. It does not run tests itself,
so the condition names output that the scripts print.

## Factory memory (end of every session, either room)

```
Before ending this session, update NOTES.md with what was confirmed, what is still unknown, which checks exist, and the next experiment to run. Commit it.
```
