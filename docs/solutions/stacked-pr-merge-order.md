---
title: Merging a stacked PR without orphaning its children
date: 2026-08-19
category: git
---

# Merging a stacked PR without orphaning its children

Deleting a parent branch on merge **auto-closes every PR based on it**, and if you then force-push the orphaned child's head, GitHub refuses to reopen it forever:

> state cannot be changed. The `<branch>` branch was force-pushed or recreated.

That combination cost PR #31, which had to be re-opened as #32 with identical content.

## The order that works

1. **Retarget children first.** Before merging the parent, point each child PR at the parent's own base: `gh pr edit <child> --base main`.
2. **Then merge the parent.** `--delete-branch` is now safe, because nothing points at that branch.
3. **Then rebase each child.** After a *squash* merge the parent's individual commits are not in `main`, so a plain `git rebase main` replays them and conflicts. Replay only the child's own commits: `git rebase --onto origin/main <last-parent-commit> <child-branch>`.

## If a child is already auto-closed

Retarget and reopen **before** touching its head. Once the head is force-pushed, the PR is unrecoverable and a new one is the only option — so do the reopen first, force-push second.

## Related

The same squash-merge asymmetry is why `git rebase main` conflicts on a stacked branch even when nothing genuinely conflicts: `main` holds one squashed commit where the branch holds the originals.
