# 0026. Evolve the submission repository into the production platform

- Status: Accepted
- Date: 2026-09-27
- Origin: the production LLMOps project that follows the interview exercise; the
  24-month KTP implementation plan (staged rollout, shared data store, evaluation
  harness)

## Context

This repository held the interview submission: a single-user assistant on SQLite
with a command line, a server-rendered page and a JSON endpoint, measured on a
frozen set and two held-out sets. The next project needs a system a company can
run: a typed web frontend, a multi-user backend, observability, repeatable
releases and a corpus that covers every official source, not 68 pages. The
earlier rule kept the submission untouched; it was set for the interview and no
longer serves.

Earlier decision records (0001–0025) live with the development history outside
this repository. This record is the first kept here.

## Decision

- Build the platform in this repository, in place, on feature branches merged
  into `main` by pull request.
- Keep the submission reproducible: the annotated tag `v5-baseline` marks
  `377a4fe` (the submitted system with its held-out grades), and every change is
  measured against it.
- Python stays at the repository root so every existing command keeps working;
  the frontend (`web/`), deployment (`deploy/`), migrations and records are added
  beside it.
- Only code and hashes are committed. Answer keys, crawled pages, model files,
  secrets and staff or customer data stay in git-ignored folders. The measurement
  harness records every key's and run's SHA-256 in `evaluation/sets.json`, so a
  changed key is caught before anything is scored.
- The measurement harness comes first (gate X0: it must reproduce the published
  numbers exactly before any engine change is measured with it).

## Consequences

- Reviewers of the interview submission use the `submission-v2` and
  `v5-baseline` tags; `main` moves on.
- The repository is public. Before any Lime Green internal document, enquiry,
  credential or staff-only material exists, the owner decides whether it becomes
  private.
- The page previously served from this folder at login must be served from a
  worktree of `v5-baseline`, or it will run whatever `main` holds.
- Every later design change is a new record here, numbered from 0027.
