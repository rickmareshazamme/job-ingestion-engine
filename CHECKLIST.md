# ZammeJobs — active checklists

**Last updated:** 2026-04-27 by Claude. Both lists live here so we can refer back at any time. Tick items off as they're done; both Claude and Rick edit this file.

---

## 👤 Rick's list — manual things only you can do

These need a human in a dashboard, browser, or partner form. Claude can't do these without your credentials.

### Activation tasks (one-time, ~30 min total)

- [ ] **Generate IndexNow key** at https://www.indexnow.org/ → paste as `INDEXNOW_KEY` Railway env var on **all three services** (web, worker, beat)
  - Why: instant Bing/Yandex/Naver/Seznam indexing on every new job (free, automatic)
  - Already wired in code — just needs the key

- [ ] **Set up Google Indexing API**
  - Create a new GCP project at https://console.cloud.google.com/
  - Enable "Indexing API"
  - Create a service account, download JSON key
  - Verify domain ownership in Google Search Console (https://search.google.com/search-console)
  - Add the service account email as Owner on the verified property
  - Paste the JSON content as `GOOGLE_SA_FILE` Railway env var on **all three services**
  - Why: Google for Jobs fast-track index slot (free 200 URL submissions/day)

- [ ] **Google Search Console** — add `https://web-production-10b8.up.railway.app` (or zammejobs.com once DNS is set) as a property → submit `/sitemap.xml`

- [ ] **Bing Webmaster Tools** at https://www.bing.com/webmasters → add site → submit `/sitemap.xml`

- [ ] **DNS — point `zammejobs.com` at Railway**
  - Railway dashboard → web service → Settings → Networking → Custom Domain → add `zammejobs.com`
  - Add the CNAME record at your DNS provider (instructions appear in the Railway dashboard)
  - Why: until done, AI engines learn the random Railway URL as canonical, not your real domain

### Hugging Face dataset publishing

- [ ] **Create `zammejobs` HF organization** at https://huggingface.co/organizations/new
- [ ] **Create dataset** at https://huggingface.co/new-dataset → owner `zammejobs`, name `jobs`, license `cc-by-4.0`, **Public**
- [ ] **Generate HF write token** at https://huggingface.co/settings/tokens → role `Write` → name `gh-actions-mirror`
- [ ] **Add `HF_TOKEN` secret** to GitHub repo at https://github.com/rickmareshazamme/job-ingestion-engine/settings/secrets/actions
- [ ] **Trigger workflow once manually** at https://github.com/rickmareshazamme/job-ingestion-engine/actions/workflows/publish-hf-dataset.yml → "Run workflow" → branch main
  - From then on it auto-runs daily at 06:00 UTC

### ChatGPT / Claude / AI distribution

- [ ] **Submit ChatGPT GPT/Action**
  - Go to https://chat.openai.com/gpts/editor
  - "Configure" tab → Actions → Import from URL → `https://web-production-10b8.up.railway.app/openapi.json`
  - Set the GPT name to "ZammeJobs", description from `/.well-known/ai-plugin.json`

- [ ] **Submit to llms.txt registries** (each is a quick form / PR)
  - https://llmstxt.org
  - https://llmstxt.directory
  - https://github.com/AnswerDotAI/llms-txt (open a PR adding zammejobs.com)

### Distribution-partner write-side flip

These are 1–4 week approval processes per platform. Once approved, set `FEED_SECRET_<UPPERCASE>` Railway env var per partner and give them `https://zammejobs.com/api/v1/feed/inbound/{slug}`.

- [ ] **Apply to VONQ Channel Partner Program** at https://www.vonq.com/become-channel-partner
- [ ] **Apply to Veritone Broadbean partner program** at https://veritone.com/products/broadbean
- [ ] **Apply to idibu partners** at https://idibu.com/partners
- [ ] **Apply to eQuest** (covered by VONQ — same form)

Each platform onboarded = thousands of additional ATS customers' jobs flowing into ZammeJobs automatically.

### Tier-2 ATS / staffing / government API tokens (connectors built, blocked on auth)

The 6 new connectors (iCIMS / SuccessFactors / Taleo / Bullhorn / EURES / Bundesagentur) are code-complete but their public APIs have all moved to OIDC-style auth between when the public docs were written and now. Each is producing 0 jobs until tokens/subdomain lists are obtained. Connectors self-disable cleanly on 401/404 so they don't break crawls.

- [ ] **iCIMS — curated customer subdomain list.** Bare slugs 404. Real customers use vanity URLs (e.g. `careers.somecompany.com` powered by iCIMS, not `careers-{slug}.icims.com`). Need to find ~100 real iCIMS customer career sites and put them in `data/icims_confirmed.txt` (one subdomain per line). Source: https://icims.com/customers, LinkedIn searches, Wappalyzer ATS detector.
- [ ] **SAP SuccessFactors — curated customer subdomain list.** Same pattern. Put real `{customer}.successfactors.com` subdomains in `data/successfactors_confirmed.txt`.
- [ ] **Oracle Taleo — curated customer subdomain list.** `data/taleo_confirmed.txt` with `{customer}.taleo.net/{section_id}`.
- [ ] **Bullhorn partner BhRestToken** — register at https://www.bullhorn.com/partners/. Get a partner token + per-customer corpToken. Set as `BULLHORN_PARTNER_TOKEN` Railway env var.
- [ ] **EURES API OIDC client** — register at https://europa.eu/eures/portal/jv-se/index. Get OIDC client_id + client_secret. Set as `EURES_CLIENT_ID` + `EURES_CLIENT_SECRET` Railway env vars (connector needs a small update to use them).
- [ ] **Bundesagentur OIDC client** — register at https://jobsuche.api.bund.dev/. Get OIDC client credentials for the `jobboerse-jobsuche` scope. Set as `BUNDESAGENTUR_CLIENT_ID` + `BUNDESAGENTUR_CLIENT_SECRET`.

### Optional / nice-to-have

- [ ] **Submit to Google Dataset Search** (auto-discovers from `/data/manifest.json` once Google indexes the site)
- [ ] **Add a Twitter/X account** `@zammejobs` (referenced in `/humans.txt`)
- [ ] **`hello@zammejobs.com` email** — set up an inbox so the contact addresses on the site work
- [ ] **`/legal` page** — privacy + terms (currently linked but missing)

---

## 🤖 Claude's list — what I should keep working on

Code/infrastructure only. I'll tick these off as they ship.

### Active / next-up

- [ ] **Common Crawl first run** — refired after connector deploys killed the previous run. Verify completion + DB count once finished. ~10–20 min.
- [ ] **Live ticker on homepage** — currently shows "recent jobs" via SQL on every page load; could be cached for 60s to reduce DB load when traffic grows.
- [ ] **Wire OIDC token-exchange into Bullhorn / EURES / Bundesagentur connectors** once Rick gets credentials (small update — add `_get_oauth_token` method, refresh on 401).
- [ ] **Build a `data/icims_confirmed.txt` seed** — script that probes the Wappalyzer iCIMS-customer list. Same for SuccessFactors and Taleo. Could automate ~50% of the manual list-curation Rick needs to do.

### Future / deferred (with reason)

- [ ] **Tune crawl cadence** — currently using defaults (per-source 6h, liveness sweep hourly with 500 sample, stale cutoff 7d). Revisit when traffic justifies.
- [ ] ~~Add iCIMS, SAP SuccessFactors, Oracle Taleo, BrassRing connectors (Tier 2 of PLAN.md)~~ — iCIMS + SuccessFactors + Taleo SHIPPED this session; BrassRing still deferred.
- [ ] **Add JSearch (RapidAPI, $30/mo)** — pulls aggregated LinkedIn/Indeed/Glassdoor data we can't get directly. Cheapest fastest +5M jobs.
- [x] ~~Add Bullhorn public API — staffing-platform jobs (~500K–1M).~~ — see "Done in this session"
- [x] ~~EURES + German Bundesagentur connectors — ~3M EU government jobs.~~ — see "Done in this session"
- [ ] **Region pages** — `/in/au/sydney`, `/in/us/sf` (city-level SEO long-tail).
- [ ] **Employer detail pages** — currently `/employers` lists; missing `/employers/{slug}`.
- [ ] **Multi-language descriptions** — for `/in/de`, `/in/fr`, `/in/jp` — auto-translate with cached results.
- [ ] **`/legal`, `/privacy`, `/terms`** stub pages so the AI plugin manifest doesn't 404.
- [ ] **Daily diff feed at `/data/daily.jsonl.gz`** — for AI labs that want incremental.
- [ ] **Hot-source override** — admin endpoint to bump crawl frequency for a single source_config without SQL.
- [ ] **Bigger AI test surface** — `/data/sample.jsonl` (1K hand-picked jobs) for AI labs to evaluate quickly.

### Done in this session

- [x] **Bullhorn + EURES + Bundesagentur connectors** — staffing #1 ATS + EU/German government feeds. Code-complete; live smoke tests revealed all three upstreams have moved to OIDC-style auth in 2025/2026 — connectors implement the documented public spec and self-disable cleanly on 401/404. Token discovery + per-customer corp tokens are now Rick-list items.
- [x] iCIMS, SAP SuccessFactors, Oracle Taleo connectors + discovery scripts (Tier-2 enterprise ATS) — ~3–6M jobs unlocked
- [x] Rebrand JobIndex → ZammeJobs (4d570e8)
- [x] start.sh branching for worker/beat (6d924c7)
- [x] AI distribution layer: robots.txt, sitemaps, llms.txt, ai.txt, citation.bib, MCP, ChatGPT plugin, IndexNow + Google Indexing modules (2314536, f8347c9)
- [x] Country routing /in/{country}/* for 23 ISOs (7acfa97)
- [x] /data/jobs.jsonl + /data/manifest.json (7acfa97)
- [x] Common Crawl harvester production-grade streaming (caf2d95)
- [x] UX upgrade: homepage ticker/country grid/employer logos, search filters, job detail similar-jobs (55e2a58)
- [x] /apply/{id} liveness redirect (d9f10f6)
- [x] Hourly liveness sweep Celery task (d9f10f6)
- [x] Inbound XML/JSON feed endpoint for VONQ/Broadbean/idibu/eQuest (047b6ee)
- [x] HF dataset auto-publisher GitHub Action (f8347c9)
- [x] Greenhouse HTML unescape fix + 10,550-row backfill (288fda1)
- [x] v0.2.0 GitHub release tagged with full changelog
- [x] Auto-memory updated for future sessions

---

**How to use this file:** Open it any time you want to know what's next. Both Claude and Rick can edit it. After completing an item, change `[ ]` to `[x]` and move it under "Done" if it's mine, or just tick it if it's yours.
