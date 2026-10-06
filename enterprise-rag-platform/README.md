# Enterprise RAG Evaluation Platform

A production-shaped document-intelligence platform that answers questions from authorized evidence, returns verifiable citations, abstains when support is insufficient, and regression-tests retrieval and generation quality.

## Deployable systems

### 1. Ingestion and indexing

`services/ingestion` exposes a document API and runs a separate ARQ worker. It accepts PDF, DOCX, HTML, JSON, CSV, Markdown, and text; stores immutable originals; creates versioned chunks; generates embeddings; builds PostgreSQL full-text indexes; records metadata and ACLs; and activates an index only after processing completes.

### 2. Serving and evaluation

`services/serving` authenticates a tenant principal, enforces role access inside each retrieval query, runs lexical/vector/hybrid retrieval, applies reciprocal-rank fusion, generates citation-bound answers, validates citation identifiers, abstains when evidence is weak, and exposes deterministic evaluation metrics.

The services share only the `rag_core` contract package and the database schema. They have separate Dockerfiles and can be released, scaled, and rolled back independently.

## Quick start

Requirements: Docker Desktop or Docker Engine with Compose.

```bash
cp .env.example .env
# Add OPENAI_API_KEY to .env for real embeddings and generation.
docker compose up --build
```

Open:

- UI: http://localhost:3000
- Serving API docs: http://localhost:8000/docs
- Ingestion API docs: http://localhost:8001/docs

If the UI reports `Failed to fetch`, verify `http://localhost:8000/health` first,
then rebuild the UI after changing `NEXT_PUBLIC_API_URL`; public Next.js variables
are embedded during `next build`. For a remote deployment, set both
`NEXT_PUBLIC_API_URL` and `CORS_ORIGINS` to the browser-visible HTTPS origins.

The no-key mode is deliberately limited: it produces zero vectors and an extractive first-passage answer so the system can be exercised locally. Do not use that mode for quality results.

## Upload a document

Use a stable tenant UUID and assign at least one role:

```bash
curl -X POST http://localhost:8001/v1/documents \
  -H 'x-tenant-id: 00000000-0000-0000-0000-000000000001' \
  -F 'file=@policy.pdf' \
  -F 'title=Security Policy' \
  -F 'allowed_roles=reader,compliance' \
  -F 'chunk_size=500' \
  -F 'chunk_overlap=75'
```

Poll the returned `job_id` at `GET /v1/ingestion-jobs/{job_id}`.

## Controlled bulk acquisition

The acquisition layer imports only explicitly registered HTTPS sources. It validates every
hostname against `ACQUISITION_ALLOWED_HOSTS`, rejects credentials and private-network
destinations, revalidates redirects, limits response size, hashes every payload, and retains
changed content as a new document version. An unchanged source is recorded as `skipped`.

Import the starter U.S. commercial-drone source registry:

```bash
curl -X POST http://localhost:8001/v1/sources/import \
  -H 'content-type: application/json' \
  -H 'x-tenant-id: 00000000-0000-0000-0000-000000000001' \
  --data-binary @samples/us_commercial_drone_sources.json
```

Review the registered sources before acquisition:

```bash
curl -H 'x-tenant-id: 00000000-0000-0000-0000-000000000001' \
  http://localhost:8001/v1/sources
```

Queue every enabled source, or pass a `source_ids` array to acquire a subset:

```bash
curl -X POST http://localhost:8001/v1/acquisitions \
  -H 'content-type: application/json' \
  -H 'x-tenant-id: 00000000-0000-0000-0000-000000000001' \
  -d '{}'
```

Poll each returned run at `GET /v1/acquisition-runs/{run_id}`. When its status is
`downloaded`, poll the associated `ingestion_job_id` until indexing is `completed`.
`skipped` means the fetched bytes match a previously indexed snapshot. Scheduled refreshes
run hourly and enqueue sources whose individual refresh interval has elapsed.

The supplied manifest is a reviewed starting registry, not permission to crawl every link
found on those pages. Add individual official documents as separate source records after
checking publication date, relevance, licensing, and retention terms. This prevents a broad
crawl from importing navigation pages, duplicates, superseded guidance, or unrelated data.

## Ask a question

```bash
curl -X POST http://localhost:8000/v1/query \
  -H 'content-type: application/json' \
  -H 'x-user-id: analyst@example.com' \
  -H 'x-tenant-id: 00000000-0000-0000-0000-000000000001' \
  -H 'x-roles: reader,compliance' \
  -d '{"question":"How long must audit logs be retained?","retrieval_mode":"hybrid","top_k":8}'
```

Trusted identity headers are a local-development boundary. In production, put the APIs behind an OIDC-aware gateway and derive tenant and roles from verified token claims—never directly from client-provided headers.

## Retrieval design

- Lexical retrieval uses PostgreSQL `tsvector` and `websearch_to_tsquery`.
- Vector retrieval uses pgvector cosine distance and an HNSW index.
- Hybrid retrieval fuses independent rankings with reciprocal rank fusion.
- ACL predicates are applied inside both database queries before fusion or generation.
- Every result is restricted to the active document version.

PostgreSQL full-text ranking is not mathematically identical to BM25. If strict BM25 is a requirement, replace the lexical adapter with ParadeDB or OpenSearch while keeping the same fusion contract.

## Evaluation

`POST /v1/evaluations/score` accepts golden cases and retrieved rankings and reports:

- Recall@5
- Recall@10
- Mean reciprocal rank
- nDCG@10

Extend evaluation runs with claim-level judgments to calculate citation precision/recall, grounded-answer rate, unsupported-claim rate, answer coverage, p50/p95 latency, and cost per successful answer. Keep groundedness paired with coverage: an always-abstain system is grounded but useless.

The example golden dataset is in `samples/golden_dataset.jsonl`. Replace placeholder chunk IDs after indexing a stable evaluation corpus. Use a development split for tuning and a held-out split for CI.

## Regression policy

The included GitHub Actions workflow runs unit tests, linting, and independent container builds. For a production gate, compare a candidate run to an approved baseline and fail when:

- Recall@5 drops by more than 0.02.
- Recall@10 drops by more than 0.01.
- Citation correctness drops by more than 0.02.
- Unsupported-claim rate increases by more than 0.01.
- Any unauthorized chunk is retrieved.
- p95 latency increases by more than 15%.
- Cost per successful answer increases by more than 10%.

Run the fast retrieval subset per pull request and the full model-based evaluation nightly to control cost and nondeterminism.

## Security hardening before production

1. Replace trusted headers with verified OIDC/JWT claims.
2. Add PostgreSQL row-level security as defense in depth.
3. Use managed object storage with encryption and retention policies.
4. Put secrets in a cloud secret manager rather than `.env`.
5. Add malware scanning, file-size limits, decompression-bomb defenses, and OCR timeouts.
6. Treat document text as untrusted input and test prompt-injection attacks.
7. Persist complete query traces without storing chain-of-thought.
8. Add deletion workflows that remove originals, chunks, embeddings, caches, and traces according to policy.

## Repository map

```text
services/ingestion/       upload API, parsers, chunking, async index worker
services/serving/         secure retrieval, generation, citations, evaluation API
packages/rag_core/        versioned contracts, fusion, metrics, validators
infra/postgres/init.sql   pgvector schema and indexes
ui/                       Next.js evidence-first interface
tests/                    deterministic regression tests
.github/workflows/        CI checks and independent image builds
```

## Important limitations

This is a runnable portfolio-grade foundation, not a claim of production certification. OCR fallback, a production cross-encoder, durable trace persistence, human evaluation workflows, full JWT validation, RLS policies, strict BM25, and cloud infrastructure modules are explicit next increments. Keeping these gaps visible is more credible than presenting an unvalidated demo as enterprise-ready.
