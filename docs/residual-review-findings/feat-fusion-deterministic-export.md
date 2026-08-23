# Residual Review Findings — feat/fusion-deterministic-export (issue #24)

Source: ce-code-review run 20260818-221854-3c4a50ea (6 reviewers: correctness, adversarial [in-process fallback; cross-model peer prohibited by user Claude-only constraint], testing, maintainability, agent-native, project-standards). All gated_auto findings were applied in-branch. The advisory residuals below are recorded here as the durable sink (no tracker tickets filed; several overlap already-open issues #18/#23).

- P1/advisory — src/fusion_design/export_handoff.py (staleness gate) — Bounds-equal topology drift passes the freshness gate; extending the binding with per-part solid volume would tighten it. Overlaps issue #18 (printable-part identity) and #23 (variant evidence).
- P2/advisory — export transaction — Verification report bytes are not archived beside the exports; the index's verification_report_sha256 can outlive the report file. Candidate improvement when #23's batch evidence lands.
- P2/advisory — export transaction — No _pump_events during the export loop; a document switch mid-export after resolution is undetected. Export is read-only w.r.t. the design; resolution/staleness checks run post-pump.
- Note — duplicate-body-name fail-closed branch may be unreachable in live Fusion (the UI auto-uniquifies body names; live negative test exercised the multiple-solids branch instead). The guard stays for API-created duplicates.
- Note — os.access(W_OK) can mis-report on ACL/cloud-synced filesystems; failure still lands fail-closed later as export-incomplete.
- Post-merge obligation (AGENTS.md release coupling): repin the marketplace — scripts/repin agent-utilities <merge-sha> 0.7.0 from a novotnyllc/marketplace checkout.
