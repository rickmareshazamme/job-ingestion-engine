# Submit ZammeJobs to search & AI engines

Concrete dashboard steps. Do these once. Each takes a few minutes.
Production base URL: `https://web-production-10b8.up.railway.app`
(swap for `https://zammejobs.com` once DNS cuts over).

---

## 1. Hugging Face dataset (highest leverage)

This is the LLM-training distribution play. Do it first.

1. Sign in at <https://huggingface.co/join> with the `zammejobs` org (create the org if it doesn't exist).
2. Create the dataset repo: <https://huggingface.co/new-dataset>
   - Owner: **zammejobs**
   - Dataset name: **jobs**
   - License: **cc-by-4.0**
   - Private: **No**
3. Generate a write token: <https://huggingface.co/settings/tokens> → "New token" → role **Write** → name `gh-actions-mirror`. Copy it.
4. Add it to this GitHub repo's secrets:
   - Repo → Settings → Secrets and variables → Actions → New repository secret
   - Name: **`HF_TOKEN`** (must be exactly this)
   - Value: paste the token
5. Trigger the workflow once manually:
   - Repo → Actions → "Publish ZammeJobs dataset to Hugging Face" → **Run workflow** → branch `main`.
6. Verify: <https://huggingface.co/datasets/zammejobs/jobs> shows `jobs.jsonl.gz`, `manifest.json`, and the rendered README.
7. From now on it auto-runs daily at 06:00 UTC.

---

## 2. Google Search Console

1. Open <https://search.google.com/search-console>.
2. Add property → URL prefix → `https://zammejobs.com` (or the Railway URL).
3. Verify via DNS TXT (preferred) or the HTML file method.
4. Sitemaps → Add a new sitemap → `sitemap.xml`.
5. Submit individually as well: `sitemap-jobs.xml`, `sitemap-employers.xml`, `sitemap-static.xml`.
6. Use **URL Inspection** to request indexing for `/`, `/search`, `/for-ai`, `/employers`, `/llms.txt`.

### Google Jobs eligibility

Google Jobs reads `JobPosting` JSON-LD from `/jobs/{id}` pages — already shipping. To accelerate detection: in Search Console, paste a job detail URL into URL Inspection → **Test live URL** → confirm "Job posting" shows under detected items → **Request indexing**.

---

## 3. Bing Webmaster Tools

1. <https://www.bing.com/webmasters>.
2. Add site → import from Google Search Console (one click) or add manually.
3. Sitemaps → Submit sitemap → `https://zammejobs.com/sitemap.xml`.
4. URL Submission → paste `/`, `/search`, `/for-ai`, `/employers`. (Quota: 10,000 URLs/day.)
5. Bing also feeds ChatGPT browse and DuckDuckGo — high leverage.

---

## 4. IndexNow (Bing + Yandex + others)

IndexNow pushes URL changes instead of waiting for crawls.

1. Generate a key: any 8-128 hex chars. Suggested: `python3 -c "import secrets; print(secrets.token_hex(16))"`.
2. Set the env var on Railway: `INDEXNOW_KEY=<the-key>` in the service's variables tab → redeploy.
3. Verify the ownership file: `https://zammejobs.com/indexnow-key.txt` returns the key.
4. Submit a URL:
   ```bash
   curl -sS "https://api.indexnow.org/indexnow?url=https://zammejobs.com/&key=<KEY>"
   ```
5. Bulk submit (up to 10k URLs/payload):
   ```bash
   curl -sS -X POST https://api.indexnow.org/indexnow \
     -H "Content-Type: application/json" \
     -d '{"host":"zammejobs.com","key":"<KEY>","keyLocation":"https://zammejobs.com/indexnow-key.txt","urlList":["https://zammejobs.com/","https://zammejobs.com/search","https://zammejobs.com/for-ai"]}'
   ```

---

## 5. ChatGPT — Action / Custom GPT

1. Open <https://chatgpt.com/gpts/editor>.
2. Configure → Name: **ZammeJobs**. Description: "Search the global job index from corporate ATS platforms — invisible to other job sites."
3. Add actions → **Import from URL** → paste:
   ```
   https://web-production-10b8.up.railway.app/openapi.json
   ```
4. Authentication: **None**.
5. Privacy policy: `https://zammejobs.com/legal`.
6. Test prompts in the right pane:
   - "Remote senior backend engineer jobs over $150K"
   - "Hiring in Berlin for product designers right now"
7. Publish → **Anyone with link** (or Public — submit to GPT Store).

The plugin manifest (`/.well-known/ai-plugin.json`) is also a valid import URL if the OpenAPI flow asks for it.

---

## 6. Anthropic / Claude — well-known feed

Anthropic doesn't run a public submission portal yet, but they crawl `/llms.txt` and `/.well-known/llm-info` automatically.

1. Confirm both are live:
   - `curl https://zammejobs.com/llms.txt`
   - `curl https://zammejobs.com/.well-known/llm-info`
2. Email `partnerships@anthropic.com` (low-effort heads-up — they don't always reply, but it gets us on the list).
3. For Claude Desktop users: link them to `/for-ai` — it has the copy-paste MCP config.

---

## 7. Common Crawl (LLM training data foundation)

Common Crawl crawls the open web monthly; their dumps feed almost every LLM training pipeline. We can't "submit" but we can maximize discoverability:

- Make sure `CCBot` is allowed in `/robots.txt` (it is — see `src/api/sitemap.py` `AI_ALLOWLIST`).
- Make sure inbound links exist from popular domains (post on Hacker News, Product Hunt, Reddit r/cscareerquestions, employer announcements).
- Confirm sitemaps are accessible without auth.

---

## 8. Other AI engines (lower effort, lower yield)

- **Perplexity** — no submission portal. They crawl `PerplexityBot`, allowed.
- **You.com** — no submission portal. `YouBot` allowed.
- **Brave Search** — submit at <https://search.brave.com/help/webmaster-guidelines>.
- **Kagi** — they index automatically from open web, but you can email `support@kagi.com` to flag the structured-data feed.
- **Mojeek** — submit at <https://www.mojeek.com/about/submission>.

---

## 9. Verification checklist

After submitting, run this from a clean machine:

```bash
BASE=https://zammejobs.com
for path in /robots.txt /sitemap.xml /sitemap-jobs.xml /sitemap-employers.xml \
            /llms.txt /.well-known/llm-info /.well-known/ai-plugin.json \
            /.well-known/mcp /ai.txt /humans.txt /citation.bib \
            /data/manifest.json /openapi.json /for-ai; do
  printf "%-40s -> " "$path"
  curl -sS -o /dev/null -w "%{http_code}\n" "$BASE$path"
done
```

Every line should return `200`.

---

## 10. Ongoing

- Check Search Console weekly for indexing errors.
- Check the GitHub Actions run history weekly — daily HF mirror should be green.
- When you cut over to `zammejobs.com` apex DNS, re-submit the sitemaps in Google + Bing under the new origin (the production Railway URL stays as a backup).
