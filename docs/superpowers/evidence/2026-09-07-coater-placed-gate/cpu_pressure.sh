#!/usr/bin/env bash
# CPU pressure on this box, as the mean number of RUNNABLE processes over five
# one-second samples.  NOT a load average: this box has 128 cores and its load
# average is dominated by disk I/O wait, so `uptime` says "busy" when every core
# is idle.  Under 64 is not busy.  Recorded beside each arm; never waited on.
vmstat 1 6 | tail -n 5 | awk '{sum+=$1} END {print sum/5}'
