#!/usr/bin/env bash
# Takes observability live, or brings it back in step: the evaluator, and the trends page
# behind the team sign-in. Every step can run again. From this repository's root, on a
# machine on Sustenaut's admin tailnet:
#
#   ./with-secrets k8s/admin/go-live.sh
#
# It needs, in Bitwarden's Sustenaut project, observability-reader-key and every name
# pubkit.json's secrets list gives; the repository variables pubkit.json's variables
# block names (not secrets, so not in Bitwarden; the owner's state repository keeps
# them); gh signed in as an admin of Sustenaut/observability; root SSH to the server;
# and, for the sign-in client, checkouts of Sustenaut/auth and Sustenaut/shared-infra
# beside this one. It prints no secret.
#
# The page's cookie secret, observability-cookie-secret, it makes itself the first time:
# when Bitwarden hasn't got it, it asks at a hidden prompt for an access token that may
# write to the project, makes 32 random bytes (openssl rand -base64 32), and writes them
# there with Bitwarden's SDK, through the pubkit this repository pins (bws would take the
# value on its command line, where every local user can read it). Neither the token nor
# the value is printed or put on disk. This comes before step 0, so stopping here
# changes nothing; later runs read the secret through ./with-secrets.
#
#   0. the variables are set, or it stops and says how to set them
#   1. the namespace observability and its deploy identity (the server's sustenaut-app)
#   2. the BigQuery key, as the Secret evaluator-bigquery-key: the deploy identity may
#      not manage Secrets, so it goes over the admin key, as everything here but 5 does
#   3. the page's cookie secret, as the Secret observability-page-secrets, and the network
#      policy that lets only the sign-in proxy reach the page
#   4. the sign-in client, as the Secret observability-oidc: register-client.sh, until
#      the Secret is there. Registering takes an approval record merged into shared-infra
#      and applied: when it is waiting for that, this stops, and running it again goes on
#   5. the repository's secrets and deploy settings, from Bitwarden: pubkit app-secrets
#   6. DEPLOY_OBSERVABILITY on, a deploy, and its wait
#   7. one run of the evaluator now, and its log; and whether the page answers
set -euo pipefail

: "${OBSERVABILITY_READER_KEY:?not set: run this through ./with-secrets, after making the key}"
server=${SUSTENAUT_SERVER:-sustenaut}
repo=Sustenaut/observability
root=$(cd "$(dirname "$0")/../.." && pwd)
k() { ssh "root@$server" "k3s kubectl -n observability $*"; }

# Writes a new observability-cookie-secret to Bitwarden and leaves it in
# OBSERVABILITY_COOKIE_SECRET, or stops. The token and the value reach pubkit's SDK
# write on its standard input, never a command line.
make_cookie_secret() {
  local token listed project wheel
  echo "observability-cookie-secret isn't in Bitwarden, so this makes it."
  read -rsp "Bitwarden access token with write access to Sustenaut (Enter to stop): " token < /dev/tty
  echo
  [ -n "$token" ] || { echo "go-live: no token, so no cookie secret, and nothing was changed" >&2; exit 1; }
  listed=$(BWS_ACCESS_TOKEN=$token bws project list --output json --color no 2> /dev/null) \
    || { echo "go-live: bws couldn't list projects with that token" >&2; exit 1; }
  project=$(jq -r '[.[] | select(.name == "Sustenaut")] | if length == 1 then "\(.[0].id) \(.[0].organizationId)" else empty end' <<<"$listed")
  [ -n "$project" ] || { echo "go-live: that token's machine account doesn't see one project named Sustenaut" >&2; exit 1; }
  # bws lists the values too; they stay in this variable.
  listed=$(BWS_ACCESS_TOKEN=$token bws secret list "${project%% *}" --output json --color no 2> /dev/null) \
    || { echo "go-live: bws couldn't list Sustenaut's secrets with that token" >&2; exit 1; }
  if jq -e 'any(.[]; .key == "observability-cookie-secret")' <<<"$listed" > /dev/null; then
    echo "go-live: observability-cookie-secret is in Bitwarden, but ./with-secrets didn't read it:" \
      "give its read-only machine account access to it, and run this again" >&2
    exit 1
  fi
  OBSERVABILITY_COOKIE_SECRET=$(openssl rand -base64 32)
  wheel=$(sed -n 's/.*--from "\([^"]*\)".*/\1/p' "$root/pubkit")
  printf '%s\n%s\n%s\n' "$token" "$project" "$OBSERVABILITY_COOKIE_SECRET" | uvx -q --from "$wheel" python -I -c '
import sys
from pubkit.bitwarden import WriteFailed, ensure, write
token, ids, value = sys.stdin.read().split("\n")[:3]
project, organization = ids.split(" ")
if why := ensure():
    sys.exit(f"go-live: {why}")
try:
    write(token, organization, project, "observability-cookie-secret", value,
          "The trends page cookie secret (oauth2-proxy), made by observability k8s/admin/go-live.sh")
except WriteFailed as error:
    sys.exit(f"go-live: Bitwarden refused observability-cookie-secret: {error}")
'
  unset token listed
  echo "wrote observability-cookie-secret to Bitwarden"
}

[ -n "${OBSERVABILITY_COOKIE_SECRET:-}" ] || make_cookie_secret

echo "0/7 the variables"
set_already=$(gh variable list -R "$repo" --json name -q '.[].name')
for name in OBSERVABILITY_DATASETS OBSERVABILITY_SENDERS; do
  grep -qx "$name" <<<"$set_already" || {
    echo "go-live: $name isn't set on $repo. Set it with gh variable set $name -R $repo --body '...'" \
      "(README.md, \"Deploying\"), or from the owner's state repository, and run this again." >&2
    exit 1
  }
done

echo "1/7 the namespace and its deploy identity"
ssh "root@$server" sustenaut-app observability

echo "2/7 the BigQuery key, as the Secret evaluator-bigquery-key"
# pubkit service-account-key create stores a key base64-encoded, as Google gives it.
printf '%s' "$OBSERVABILITY_READER_KEY" | base64 -d | ssh "root@$server" \
  'k3s kubectl -n observability create secret generic evaluator-bigquery-key --from-file=key.json=/dev/stdin --dry-run=client -o yaml | k3s kubectl apply -f -'

echo "3/7 the page's cookie secret, and its network policy"
# oauth2-proxy decodes the secret only as URL-safe base64: a standard one with + or / in
# it is taken as 44 raw bytes, which it refuses. The same 32 bytes, URL-safe, it takes.
printf '%s' "$OBSERVABILITY_COOKIE_SECRET" | tr '+/' '-_' | ssh "root@$server" \
  'k3s kubectl -n observability create secret generic observability-page-secrets --from-file=cookie-secret=/dev/stdin --dry-run=client -o yaml | k3s kubectl apply -f -'
ssh "root@$server" 'k3s kubectl apply -f -' < "$root/k8s/admin/network-policy.yaml"

echo "4/7 the sign-in client"
if k get secret observability-oidc > /dev/null 2>&1; then
  echo "the Secret observability-oidc is there"
else
  status=0
  "$root/k8s/admin/register-client.sh" || status=$?
  if [ "$status" = 3 ]; then
    echo "go-live: the sign-in client waits for its approval record: merge it into shared-infra," \
      "apply, and run this again." >&2
    exit 3
  fi
  [ "$status" = 0 ] || exit "$status"
fi

echo "5/7 the repository's secrets and deploy settings, from Bitwarden"
"$root/pubkit" app-secrets

echo "6/7 deploying"
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
# A new client or cookie secret reaches the proxy only when it starts again.
k rollout restart deployment/oauth2-proxy > /dev/null
k rollout status deployment/oauth2-proxy --timeout=120s > /dev/null

echo "7/7 one run of the evaluator now, and the page"
job="evaluator-go-live-$(date +%s)"
ssh "root@$server" "k3s kubectl -n observability create job $job --from=cronjob/evaluator > /dev/null \
  && k3s kubectl -n observability wait --for=condition=complete --timeout=150s job/$job; \
  k3s kubectl -n observability logs job/$job"
health=$(curl -s -o /dev/null -w '%{http_code}' https://observability.sustenaut.eu/healthz || true)
page=$(curl -s -o /dev/null -w '%{http_code}' https://observability.sustenaut.eu/trends/integrations/ || true)
echo "the page: /healthz answers $health, and /trends/integrations/ $page (a 302 to the sign-in is right)"
echo "go-live: done; the evaluator runs every two minutes, and the page is at" \
  "https://observability.sustenaut.eu/trends/integrations/ for people with the observability role"
