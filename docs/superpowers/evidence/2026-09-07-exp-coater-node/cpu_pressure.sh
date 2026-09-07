#!/usr/bin/env bash
# CPU pressure on this box, as the five-second mean of RUNNABLE processes.
#
# `uptime`'s load average is NOT a CPU-load figure here: this box's load is
# mostly I/O wait, so a load average of 25 can sit beside an idle CPU.  What a
# timing measurement needs is how many processes are actually runnable, which
# is vmstat's first column.  Below 64 is fine on these 128 cores, and a run is
# never delayed waiting for it to fall.
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {printf "%.1f", sum/5}'
