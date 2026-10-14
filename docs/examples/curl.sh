#!/bin/sh
# Usage: sh curl.sh [base_url]
B=${1:-https://solanastockdatabase.com}

curl -s "$B/api/health"; echo
curl -s "$B/api/stats"; echo
curl -s "$B/api/search?q=stonk"; echo
curl -s "$B/api/leaderboard/rendimento?limit=5"; echo
curl -s "$B/api/rpc-stats"; echo
