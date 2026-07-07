# Deploying quolab

quolab deploys as a **new, separate** Cloud Run service. It does **not** touch
Quorum's `quorum` service, MCP gateway, or Agent Engine (frozen until 2026-07-13).

## Prerequisites
- A Gemini API key in Secret Manager (`quolab-gemini-key`).
- Optional: a read-only GitLab PAT in Secret Manager (`quolab-gitlab-token`) — only
  needed to clone **private** target repos. Public repos clone without it.

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
  --set-secrets QUOLAB_GEMINI_API_KEY=quolab-gemini-key:latest \
  --allow-unauthenticated   # tighten /index + /gate to IAM before any public sharing
```

## Smoke test + pre-warm
```bash
URL=$(gcloud run services describe quolab --region us-central1 --format='value(status.url)')
curl "$URL/healthz"
# Pre-warm the index for a repo (writes into the warm sqlite index):
curl -X POST "$URL/index" -H 'content-type: application/json' \
  -d '{"project_id":"https://gitlab.com/group/repo"}'
curl -X POST "$URL/search" -H 'content-type: application/json' \
  -d '{"project_id":"https://gitlab.com/group/repo","query":"saga compensation"}'
```

## Notes
- `QUOLAB_STORE=sqlite` keeps the index only in the warm instance — a cold start loses
  it, so re-run `POST /index` after a scale-to-zero. For a persistent, cold-start-surviving
  index, switch to `pgvector` (provision Cloud SQL + wire `QUOLAB_PG_DSN`).
- The container installs `git` so the indexer can shallow-clone target repos.
