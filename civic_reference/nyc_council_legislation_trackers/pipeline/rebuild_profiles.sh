#!/usr/bin/env bash
# Rebuild every Agencies and Council Members data file after tracker data
# changes (profiles audit, Sep 30 2026). One script for every path that
# rewrites tracker data (monthly refresh, resume job, backfill, local sweeps):
# before this, the backfill and resume jobs rebuilt members.json and
# agencies.json only, so member_votes.json and member_context.json went stale.
#
# Runs every builder even when one fails, prints a GitHub ::error:: line per
# failure, and exits 1 at the end if any failed, so the workflow can commit
# what did build and still turn red instead of passing silently.
#
#   ARCHIVE=/path/to/nyc_legislation bash pipeline/rebuild_profiles.sh
# (run from civic_reference/nyc_council_legislation_trackers; the jehiah
# archive is cloned into $ARCHIVE when it is missing)
set -u
ARCHIVE="${ARCHIVE:-${RUNNER_TEMP:-/tmp}/nyc_legislation}"
failed=()

run() {
  echo "::group::$*"
  if ! "$@"; then
    echo "::error::profile rebuild step failed: $*"
    failed+=("$*")
  fi
  echo "::endgroup::"
}

if [ ! -d "$ARCHIVE/people" ]; then
  run git clone --depth 1 --filter=blob:none --sparse https://github.com/jehiah/nyc_legislation "$ARCHIVE"
  [ -d "$ARCHIVE/.git" ] && run git -C "$ARCHIVE" sparse-checkout set people events introduction
fi

if [ -d "$ARCHIVE/people" ]; then
  [ -f pipeline/build_council_roster.py ] && run python3 pipeline/build_council_roster.py --archive "$ARCHIVE"
else
  echo "::error::Council archive unavailable: roster, votes and context not rebuilt"
  failed+=("archive")
fi
if [ -d "$ARCHIVE/people" ]; then run python3 pipeline/build_member_stats.py --archive "$ARCHIVE"; else run python3 pipeline/build_member_stats.py; fi
run python3 pipeline/build_agency_profiles.py
if [ -d "$ARCHIVE/people" ]; then
  run python3 pipeline/build_member_votes.py --archive "$ARCHIVE"
  run python3 pipeline/build_member_context.py --archive "$ARCHIVE"
fi

if [ ${#failed[@]} -gt 0 ]; then
  echo "::error::${#failed[@]} profile rebuild step(s) failed: ${failed[*]}"
  exit 1
fi
echo "profiles rebuilt: roster, members, agencies, votes, context"
