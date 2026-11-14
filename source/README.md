# Sekelo — Construction Price Intelligence

Price-intelligence tracker for construction materials in Eswatini (SZL) and
neighbouring South African retailer branches (ZAR). Tracks Cashbuild and
Builders Warehouse prices across 4 branches, normalises them per kg/unit,
applies a 20% border premium for SZL estimates, and ships with a Bill of
Quantities multi-location cost comparator.

## Pages

| Page | Path | Description |
|---|---|---|
| Price index dashboard | `/index.html` | Password-gated, category-grouped price table with WoW deltas, search/filter, PDF + CSV export, light/dark theme |
| Price administration | `/admin.html` | Manual price entry per branch, review queue (approve / reject / schedule publication), bulk actions |
| BoQ calculator | `/boq.html` | Public. Enter material quantities, compare total cost across all 4 branches, export PDF + CSV |
| Legacy redirect | `/bill-of-quantities/` | Redirects to `/boq.html` (kept for old bookmarks) |

## Architecture

Pure static site — no build step, no framework. Host on GitHub Pages, Netlify,
Cloudflare Pages, or any static host.

```
assets/
  config.js    Supabase URL/anon key, border premium, branch list (single source of truth)
  common.js    sbGet/sbPost/sbPatch, SHA-256 gate, toast notifications, CSV export, theme
index.html     dashboard (page-specific render + PDF logic inline)
admin.html     price administration (page-specific logic inline)
boq.html       BoQ calculator (page-specific logic inline)
```

Data lives in Supabase (PostgREST). Tables: `categories`, `products`, `prices`
(history), `price_submissions` (review queue), `app_config` (gate secrets).

Run locally: `python3 -m http.server` then open `http://localhost:8000`.

## Security model — read this

The access gates are **client-side deterrents, not true authentication**. With a
static site + Supabase anon key, a determined visitor can read the JS and bypass
the gate. The improvements below raise the bar substantially; for production-grade
access control, move the gate behind Supabase Auth + RLS or an Edge Function.

### What changed (this revision)

- **Plaintext passwords removed.** The dashboard password was previously fetched
  in plaintext from `app_config` (anon-readable); the admin password was
  hardcoded in source. Both are gone.
- **Hash-aware gate** (`SekeloGate` in `assets/common.js`): stores/compares a
  SHA-256 hash of the access code, so even if `app_config` is read, no plaintext
  leaks. Falls back to plaintext compare *only* until you run the migration below.
- **Brute-force rate limit**: 5 failed attempts → 60 s lockout (per browser).
- **Secrets centralised** in `assets/config.js`. The anon key is meant to be
  public — what matters is Row Level Security.

### Migration (run once in the Supabase SQL editor)

```sql
-- 1. Dashboard access code → SHA-256 of the current code 'sekelo-cic-2026'.
UPDATE app_config
SET value = '55f8449ca97a836c8ec622535598e07a43d96664132ead953b23a1cfbd10d4cf'
WHERE key = 'dashboard_password';

-- 2. Admin password → SHA-256 of the current hardcoded 'sekelo2026'.
INSERT INTO app_config(key, value)
VALUES ('admin_password', '2e6887f4ec8d82083f9e6cc9bc6002a927cf700805b5d9aebe3fef708a694f0f')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
```

To set a *new* access code, generate its hash with `printf '%s' 'new-code-here' | sha256sum`
and UPDATE the corresponding `app_config` row.

### Recommended RLS policies (Supabase dashboard → Authentication → Policies)

- `app_config`: enable RLS; allow anon `SELECT` only (the gate reads hashes).
  Never allow anon `INSERT`/`UPDATE`/`DELETE`.
- `categories`, `products`, `prices`: anon `SELECT` only.
- `price_submissions`: anon `INSERT` is required by the admin page today, which
  means anyone can submit rows for review (they still can't publish). To close
  this, route admin writes through an Edge Function that uses the `service_role`
  key and verifies a secret, then restrict `price_submissions` to `SELECT` for anon.

## License

MIT — see `LICENSE`.
