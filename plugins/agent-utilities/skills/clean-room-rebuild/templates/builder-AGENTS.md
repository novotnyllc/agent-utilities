# Room B: builder (__SLUG__)

Clean-room rebuild, build side. Build only from SPEC.md in this folder.
Do not read ../reader or ../wall, do not use REA, and do not look for the
original app. Implementation lives in src/ and tests in tests/. Planted
failures live in oracle/mutants/*.patch, change behaviour in src/ only, and
must all be rejected by the tests (the skill's check-oracle.sh). End each
session by updating NOTES.md and committing.

This folder is the product you ship. Work directly: don't use planning,
review or delivery workflow plugins here unless the user explicitly asks.
The spec and the oracle check are the plan and the review.
