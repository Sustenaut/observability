#!/usr/bin/env bash
# Takes the evaluator live, or brings a live one back in step: every step can run again.
# From this repository's root, on a machine on Sustenaut's admin tailnet:
#
#   ./with-secrets k8s/admin/go-live.sh
#
# It needs, in Bitwarden's Sustenaut project, observability-reader-key and every name
# pubkit.json's secrets list gives; the repository variables pubkit.json's variables
# block names (OBSERVABILITY_DATASETS and OBSERVABILITY_SENDERS: not secrets, so not in
# Bitwarden; the owner's state repository keeps them); gh signed in as an admin of
# Sustenaut/observability; and root SSH to the server. It prints no secret.
#
#   0. the variables are set, or it stops and says how to set them
#   1. the namespace observability and its deploy identity (the server's sustenaut-app)
#   2. the BigQuery key, as the Secret evaluator-bigquery-key: the deploy identity may
#      not manage Secrets, so it goes over the admin key
#   3. the repository's secrets and deploy settings, from Bitwarden: pubkit app-secrets
#   4. DEPLOY_OBSERVABILITY on, a deploy, and its wait
#   5. one run of the evaluator now, rather than at the next two minutes, and its log
set -euo pipefail

: "${OBSERVABILITY_READER_KEY:?not set: run this through ./with-secrets, after making the key}"
server=${SUSTENAUT_SERVER:-sustenaut}
repo=Sustenaut/observability
root=$(cd "$(dirname "$0")/../.." && pwd)

echo "0/5 the evaluator's variables"
set_already=$(gh variable list -R "$repo" --json name -q '.[].name')
for name in OBSERVABILITY_DATASETS OBSERVABILITY_SENDERS; do
  grep -qx "$name" <<<"$set_already" || {
    echo "go-live: $name isn't set on $repo. Set it with gh variable set $name -R $repo --body '...'" \
      "(README.md, \"Deploying\"), or from the owner's state repository, and run this again." >&2
    exit 1
  }
done

echo "1/5 the namespace and its deploy identity"
ssh "root@$server" sustenaut-app observability

echo "2/5 the BigQuery key, as the Secret evaluator-bigquery-key"
# pubkit service-account-key create stores a key base64-encoded, as Google gives it.
printf '%s' "$OBSERVABILITY_READER_KEY" | base64 -d | ssh "root@$server" \
  'k3s kubectl -n observability create secret generic evaluator-bigquery-key --from-file=key.json=/dev/stdin --dry-run=client -o yaml | k3s kubectl apply -f -'

echo "3/5 the repository's secrets and deploy settings, from Bitwarden"
"$root/pubkit" app-secrets

echo "4/5 deploying"
gh variable set DEPLOY_OBSERVABILITY -R "$repo" --body on
before=$(gh run list -R "$repo" -w deploy.yml -L 1 --json databaseId -q '.[0].databaseId // 0')
gh workflow run deploy.yml -R "$repo" --ref main
run=$before
for _ in $(seq 30); do
  run=$(gh run list -R "$repo" -w deploy.yml -L 1 --json databaseId -q '.[0].databaseId // 0')
  [ "$run" != "$before" ] && break
  sleep 2
done
[ "$run" != "$before" ] || { echo "go-live: the deploy didn't start" >&2; exit 1; }
gh run watch "$run" -R "$repo" --exit-status > /dev/null

echo "5/5 one run of the evaluator now"
job="evaluator-go-live-$(date +%s)"
ssh "root@$server" "k3s kubectl -n observability create job $job --from=cronjob/evaluator > /dev/null \
  && k3s kubectl -n observability wait --for=condition=complete --timeout=150s job/$job; \
  k3s kubectl -n observability logs job/$job"
echo "go-live: done; the evaluator now runs every two minutes"
