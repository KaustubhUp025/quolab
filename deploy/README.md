# Deploying quolab

quolab deploys as a **new, separate** Cloud Run service. It does **not** touch
Quorum's `quorum` service, MCP gateway, or Agent Engine (frozen until 2026-07-13).

## Prerequisites
- A Gemini API key in Secret Manager (`quolab-gemini-key`).
- Optional: a Postgres+pgvector instance (Cloud SQL) and its DSN in Secret Manager
  (`quolab-pg-dsn`). Skip if you keep `QUOLAB_STORE=sqlite` (ephemeral on Cloud Run).

## Deploy
```bash
gcloud run deploy quolab \
  --source . \
  --region us-central1 \
  --execution-environment gen2 \
  --env-vars-file deploy/cloudrun.env.yaml \
  --set-secrets QUOLAB_GEMINI_API_KEY=quolab-gemini-key:latest \
  --set-secrets QUOLAB_PG_DSN=quolab-pg-dsn:latest \
  --allow-unauthenticated   # tighten to IAM before any public sharing
```

## Smoke test
```bash
URL=$(gcloud run services describe quolab --region us-central1 --format='value(status.url)')
curl "$URL/healthz"
curl -X POST "$URL/search" -H 'content-type: application/json' \
  -d '{"project_id":"https://gitlab.com/group/repo","query":"saga compensation"}'
```

## Notes
- `QUOLAB_STORE=sqlite` works but the index is lost on cold start — use `pgvector`
  for a persistent index in production.
- The container installs `git` so the indexer can shallow-clone target repos.
