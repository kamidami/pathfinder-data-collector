# Official programme URL discovery

Discovery starts from operator-provided official institution domains. This keeps the trust
boundary explicit: the collector does not scrape search-engine result pages, query commercial
search APIs, use third-party programme directories as evidence, or use an AI model.

The UTF-8 seed CSV requires `institution_name` and hostname-only `official_domain`. Optional
columns are `catalogue_url`, `sitemap_url`, and `operator_notes`. Explicit URLs must use HTTP(S)
and belong to the official domain or one of its subdomains. See
`docs/examples/programme_discovery_seeds.csv`.

```powershell
python -m pathfinder_collector discover programs --job-id <PROGRAM_JOB_UUID> `
  --seeds .\seeds.csv --target 50
```

For each unique domain, discovery checks an explicit sitemap, robots.txt Sitemap declarations,
conventional sitemap locations, an explicit catalogue, and then a bounded same-origin crawl.
Sitemap indexes, XML sitemaps, and bounded gzip sitemaps are supported. Processing is sequential.
Configuration strictly limits sitemap count/depth, pages per domain, crawl depth, raw links,
response size, redirects, timeouts, and retry behavior. All requests retain DNS/SSRF validation,
robots enforcement, content-type rules, and caching. Login, account, calendar, news, events,
privacy, staff, publications, search traps, media, and PDFs are excluded.

Candidates receive a transparent deterministic score and matched URL/anchor/catalogue signals.
Discovery does not assert that a URL is a programme: the existing extraction pipeline must confirm
programme content, and human review remains mandatory. Discovery never approves, verifies,
exports, imports, or writes to Pathfinder.

Reports are written beneath `var/reports/discovery/<run-id>/`:

- `discovery_summary.json` — aggregate counts and safe per-URL results;
- `discovered_programmes.csv` — direct input for `batch collect`;
- `discovery_results.csv` — scores, signals, sources, skips, and reuse reasons;
- `discovery_report.txt` — concise target/shortfall and trust summary.

Every meaningful controlled robots, sitemap, catalogue, crawl-seed, DNS, content, or access
failure is also written as a safe row in both discovery result formats. Duplicate failure attempts
with the same domain, canonical URL, discovery source, and status are collapsed. Consequently,
`controlled_failures` equals the number of reported controlled-failure rows; candidate, duplicate,
and already-existing rows are not included in that counter.

Run the generated batch input with:

```powershell
python -m pathfinder_collector batch collect --job-id <PROGRAM_JOB_UUID> `
  --file <discovery-run>\discovered_programmes.csv
```

Canonical URL deduplication spans seeds, the discovery run, and job-associated URLs. Reruns safely
reuse cached discovery pages and reproduce unique candidates without creating candidate/evidence
records. Reaching `--target` stops optional crawling; a shortfall is reported and is not an error.
