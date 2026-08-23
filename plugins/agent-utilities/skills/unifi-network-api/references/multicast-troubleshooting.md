# Multicast and mDNS Troubleshooting

## Verify end to end, hop by hop

Multicast failures rarely announce themselves. Test delivery at each hop with packet captures and join-probes instead of trusting service liveness or single-point captures.

1. Reflector/relay: capture on the source and destination bridges (`tcpdump -i <bridge> "udp port 5353 or udp port 1900"`) and confirm packets appear on the far side with their original source addresses preserved.
2. IGMP querier: `tcpdump -i <bridge> igmp` for at least 130 seconds; expect periodic general queries plus host membership reports. Note the query version — it constrains the report format clients use.
3. Wired delivery: run a join-and-listen probe on a wired host (join `224.0.0.251`, bind `:5353`, count packets and distinct sources for 10+ seconds).
4. AP wire ingress: on the AP, `tcpdump -i eth0 "udp port 5353 or udp port 1900"`.
5. VAP handoff: `tcpdump -i <vap>` on the AP. VAP interface names come from `mca-dump` `vap_table[]` (per-radio names such as `wifi0apN`, `wifi1apN`, `wifi2apN`), not `ath*`.
6. Client reception: the same join-and-listen probe on a wireless client. Frames visible at the VAP but absent at the client indicate loss in group-frame transmission or multicast-to-unicast conversion — the capture point at the VAP is upstream of that conversion.

A wired-receives / wireless-does-not split isolates the failure to the AP's wireless delivery path and exonerates relays, queriers, and switch fabric in one measurement.

## Known failure mode: Multicast to Unicast

The per-WLAN "Multicast to Unicast" setting (`wlanconf.mcastenhance_enabled`; older UIs label it "Multicast Enhancement (IGMPv3)") converts group frames into per-subscriber unicast using the AP's own IGMP subscription tracking. When that tracking is empty — observed after console/switch firmware updates that change the active IGMP querier version, forcing clients into different report formats — the conversion delivers to zero clients on every band while every upstream capture point looks healthy. Client IGMP joins are absorbed by the AP in this mode, so their absence from the wired fabric is expected and not itself a fault.

Disabling the setting per-SSID restores standard DTIM group delivery and removes the failure mode entirely. For networks whose multicast is discovery chatter (mDNS/SSDP) rather than high-rate streaming video, the conversion provides no measurable benefit: discovery volume is a few kilobytes per second, well under 1% airtime even at low basic rates.

## Reading IGMP state

- Site configuration lives in the `setting` document with key `igmp_snooping`: `querier_mode`, `querier_addresses[]` (each `{querier_address, network_id, mac}` — the `mac` designates which switch hosts the querier), `querier_switches[]`, `flood_unknown_multicast_for_network_ids[]`, `flood_known_protocols`. Per-network IGMP fields on `networkconf` are not present on current builds.
- On switches and APs, `mca-dump` returns JSON device state. `igmp_snoop_table.querier[]` shows per-VLAN querier election as `{is_querier, querier_ip, version, vlan}` — IPv4 entries are `version: 2/3`, link-local IPv6 entries are the MLD side. `vap_table[]` on APs shows per-SSID VAP interfaces with station tables.
- `swctrl` has no multicast function and `bridge mdb show` returns "Not supported" on switches; `mca-dump` is the source of truth for snooping state.
- A VLAN included in IGMP snooping without a configured querier address renders a placeholder querier in the `198.18.0.0/15` benchmark range in snoop tables. Add a querier address for the network or remove it from the snooping list.

## Device shell access

Adopted switches and APs accept SSH with the site's device authentication credential (UniFi Network → Settings → System → Device SSH / Device Authentication). Obtain that credential from the operator or their password manager and deliver it to `ssh` without it entering the transcript (for example `op run` feeding an `expect` script); never lift credentials from the controller database or paste them into chat. `tcpdump` is available on both switches and APs.

## Custom services on the console

`/data` (including `/data/on_boot.d`) survives UniFi OS updates, but updates reboot the console and can simultaneously bump switch firmware — after every update, verify custom services are running and multicast delivery still works end to end rather than assuming either. For interface-binding daemons started from `on_boot.d`, prefer the daemon's own readiness flag (for example multicast-relay's `--wait`) over external wrappers. Avoid wrapping such daemons in transient `Restart=always` units while debugging: manual kills are silently resurrected, which masquerades as instability.
