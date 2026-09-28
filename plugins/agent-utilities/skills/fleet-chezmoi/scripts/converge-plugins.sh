#!/bin/sh
# fleet-chezmoi converge-plugins: run Roundhouse's own plugin convergence now.
#
# Roundhouse fleet-run owns plugin state: it registers declared marketplaces,
# installs, updates, and enables the plugins the fleet store declares, with
# catalog-identity and hook-trust checks. It already runs every 20 minutes;
# this runs the same fast pass immediately and reports its exit status.
set -u
if ! command -v roundhouse >/dev/null 2>&1; then
  jq -cn '{schema:"fleet-chezmoi.plugins",version:1,ok:false,error:"roundhouse is not on PATH"}'
  exit 0
fi
rc=0
roundhouse fleet-run --fast >/dev/null 2>&1 </dev/null || rc=$?
jq -cn --argjson rc "$rc" '{schema:"fleet-chezmoi.plugins",version:1,ok:($rc == 0),exit:$rc}'
