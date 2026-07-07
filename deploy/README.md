# Deploying quolab

quolab deploys as a **new, separate** Cloud Run service. It does **not** touch
Quorum's `quorum` service, MCP gateway, or Agent Engine (frozen until 2026-07-13).

## Prerequisites
- A Gemini API key in Secret Manager (`quolab-gemini-key`).
- An app-layer API key in Secret Manager (`quolab-api-key`) — the `X-API-Key` gate. Every
  route except `/healthz` requires it.
- Optional: a read-only GitLab PAT in Secret Manager (`quorum-gitlab-token`) — only needed
  to clone **private** target repos. Public repos clone without it.

## Security posture (this deployment is locked down, not public)
This service holds a GitLab PAT and self-indexes (`QUOLAB_ALLOW_AUTO_INDEX=true`), so it is
**not** exposed to `allUsers`. Two layers gate it:
1. **Cloud Run IAM** — `run.invoker` is granted only to the caller's service account(s)
   (for Quorum: its Cloud Run SA + Agent Engine SA). Deploy with `--no-allow-unauthenticated`.
2. **App-layer `X-API-Key`** — defence-in-depth on top of IAM (`quolab-api-key` secret).

Do **not** add `--allow-unauthenticated` or enable `QUOLAB_ALLOW_AUTO_INDEX` on a publicly
reachable quolab.

## Deploy
Runs with the default `QUOLAB_STORE=sqlite` (zero-infra). `--min-instances 1` keeps the
in-instance index warm between requests; pre-warm target repos with `POST /index` after
each deploy (a cold start loses the index).
```bash
gcloud run deploy quolab \
  --source . \
  --region us-central1 \
  --execution-environment gen2 \
  --min-instances 1 --memory 2Gi --cpu 2 \
  --env-vars-file deploy/cloudrun.env.yaml \
  --set-secrets \
    QUOLAB_GEMINI_API_KEY=quolab-gemini-key:latest,\
QUOLAB_API_KEY=quolab-api-key:latest,\
QUOLAB_GITLAB_TOKEN=quorum-gitlab-token:latest \
  --no-allow-unauthenticated

# Grant invoke only to the caller's service account (repeat per caller):
gcloud run services add-iam-policy-binding quolab --region us-central1 \
  --member "serviceAccount:<CALLER_SA>" --role roles/run.invoker
```

## Smoke test + pre-warm
The service is IAM-locked and key-gated, so callers need both a Google identity token
(`Authorization: Bearer …`) and the `X-API-Key` header. `/healthz` is exempt from the key
gate but still behind IAM.
```bash
URL=$(gcloud run services describe quolab --region us-central1 --format='value(status.url)')
TOKEN=$(gcloud auth print-identity-token)   # identity must have roles/run.invoker
KEY=$(gcloud secrets versions access latest --secret quolab-api-key)

curl "$URL/healthz" -H "Authorization: Bearer $TOKEN"
# Pre-warm the index for a repo (writes into the warm sqlite index):
curl -X POST "$URL/index" \
  -H "Authorization: Bearer $TOKEN" -H "X-API-Key: $KEY" -H 'content-type: application/json' \
  -d '{"project_id":"https://gitlab.com/group/repo"}'
curl -X POST "$URL/search" \
  -H "Authorization: Bearer $TOKEN" -H "X-API-Key: $KEY" -H 'content-type: application/json' \
  -d '{"project_id":"https://gitlab.com/group/repo","query":"saga compensation"}'
```

## Notes
- `QUOLAB_STORE=sqlite` keeps the index only in the warm instance — a cold start loses
  it, so re-run `POST /index` after a scale-to-zero. For a persistent, cold-start-surviving
  index, switch to `pgvector` (provision Cloud SQL + wire `QUOLAB_PG_DSN`).
- The container installs `git` so the indexer can shallow-clone target repos.
