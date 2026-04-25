# JobIndex — Step-by-Step Setup Guide

## Prerequisites

- GitHub account (you have: rickmareshazamme)
- Railway account (railway.app — sign up with GitHub)
- Terminal access

---

## Step 1: Login to Railway

Open terminal and run:

```bash
cd /Users/rickmare/Desktop/ClaudeCode/job-ingestion-engine
railway login
```

This opens a browser. Click "Authorize" to link your Railway account.

Verify it worked:
```bash
railway whoami
```

---

## Step 2: Create Railway Project

```bash
railway init
```

When prompted:
- Select "Empty Project"
- Name it: `job-ingestion-engine`

---

## Step 3: Add PostgreSQL Database

Go to https://railway.app → Open your `job-ingestion-engine` project → Click "New" → "Database" → **PostgreSQL**

Wait for it to provision (~30 seconds).

Click on the PostgreSQL service → "Variables" tab → Copy the `DATABASE_URL` value. It looks like:
```
postgresql://postgres:xxxxx@xxx.railway.internal:5432/railway
```

---

## Step 4: Add Redis

Same project → Click "New" → "Database" → **Redis**

Wait for it to provision. Copy the `REDIS_URL` from the Redis service variables. It looks like:
```
redis://default:xxxxx@xxx.railway.internal:6379
```

---

## Step 5: Set Environment Variables

In Railway dashboard → Click on your app service (not the databases) → "Variables" tab → Add these:

| Variable | Value |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` (from Step 3, replace `postgresql://` with `postgresql+asyncpg://`) |
| `DATABASE_URL_SYNC` | The original PostgreSQL URL from Step 3 (keep as `postgresql://`) |
| `REDIS_URL` | The Redis URL from Step 4 |
| `PORT` | `8000` |

**Important:** Railway's PostgreSQL URL starts with `postgresql://`. For the async driver, you need TWO versions:
- `DATABASE_URL_SYNC` = the original `postgresql://...` 
- `DATABASE_URL` = same URL but replace `postgresql://` with `postgresql+asyncpg://`

---

## Step 6: Deploy the App

From your terminal:

```bash
cd /Users/rickmare/Desktop/ClaudeCode/job-ingestion-engine
railway link    # Select your project
railway up      # Deploy
```

Wait for the build to complete (~2-3 minutes). Railway will show a URL like:
```
https://job-ingestion-engine-production-xxxx.up.railway.app
```

Visit that URL — you should see the homepage.

---

## Step 7: Run Database Migration

```bash
railway run alembic upgrade head
```

This creates all the tables (employers, jobs, source_configs, crawl_runs).

Verify:
```bash
railway run python3 -c "
from sqlalchemy import create_engine, text
from src.config import settings
engine = create_engine(settings.database_url_sync)
with engine.connect() as conn:
    tables = conn.execute(text(\"SELECT tablename FROM pg_tables WHERE schemaname='public'\")).fetchall()
    print('Tables:', [t[0] for t in tables])
"
```

You should see: `['employers', 'source_configs', 'jobs', 'crawl_runs']`

---

## Step 8: Discover Greenhouse Employers

This validates 3,295 Greenhouse board tokens and saves valid ones to the database:

```bash
railway run python3 -m scripts.discover_greenhouse
```

Takes ~5 minutes. Expected output: ~1,000-1,500 valid boards found.

---

## Step 9: Load Confirmed Workday Employers

```bash
railway run python3 -m scripts.discover_workday_confirmed
```

Takes ~30 seconds. Loads 92 confirmed Workday instances (104K+ jobs).

---

## Step 10: Run the First Crawl

Quick crawl (free sources, ~1,500 jobs in 30 seconds):
```bash
railway run python3 -m scripts.first_crawl --quick
```

Full crawl (Greenhouse + Workday + free sources):
```bash
railway run python3 -m scripts.first_crawl
```

---

## Step 11: Verify Jobs Are in the Database

```bash
railway run python3 -c "
from sqlalchemy import create_engine, text
from src.config import settings
engine = create_engine(settings.database_url_sync)
with engine.connect() as conn:
    count = conn.execute(text('SELECT COUNT(*) FROM jobs')).scalar()
    employers = conn.execute(text('SELECT COUNT(*) FROM employers')).scalar()
    print(f'Jobs: {count}')
    print(f'Employers: {employers}')
"
```

---

## Step 12: Visit Your Live Site

Open the Railway URL in your browser:
- **Homepage:** `https://your-app.up.railway.app/`
- **Search:** `https://your-app.up.railway.app/search?q=engineer`
- **API:** `https://your-app.up.railway.app/api/v1/stats`
- **API Docs:** `https://your-app.up.railway.app/docs`

---

## Step 13: Set Up Automated Crawling (Optional)

To have jobs automatically refresh on a schedule, you need a Celery worker + beat process. In Railway:

1. Go to your project → "New" → "Service"
2. Connect the same GitHub repo
3. Set start command to: `celery -A src.tasks.crawl worker --loglevel=info --concurrency=2`
4. Add the same environment variables (DATABASE_URL_SYNC, REDIS_URL)

Create another service for the scheduler:
1. "New" → "Service" → same repo
2. Start command: `celery -A src.scheduler beat --loglevel=info`
3. Same environment variables

Now jobs will be re-crawled automatically every 6-24 hours.

---

## Step 14: Get Free API Keys (More Jobs)

Register for these free API keys to unlock aggregator connectors:

| Service | Sign Up URL | Add to Railway as |
|---|---|---|
| **Adzuna** (10M+ jobs, 16 countries) | https://developer.adzuna.com/ | `ADZUNA_APP_ID` + `ADZUNA_APP_KEY` |
| **USAJobs** (30K US federal jobs) | https://developer.usajobs.gov/APIRequest/Index | `USAJOBS_API_KEY` + `USAJOBS_EMAIL` |
| **Reed** (250K UK jobs) | https://www.reed.co.uk/developers | `REED_API_KEY` |

Add these as environment variables in Railway dashboard. The connectors will automatically use them.

---

## Step 15: Submit to Search Engines

Once your site has jobs, submit to search engines so AI can find them:

1. **Google Search Console:** https://search.google.com/search-console
   - Add your Railway URL as a property
   - Submit sitemap: `https://your-app.up.railway.app/sitemap.xml`

2. **Bing Webmaster Tools:** https://www.bing.com/webmasters
   - Add your site
   - Submit sitemap

3. **IndexNow** (automatic — built in, just needs the key):
   - Add `INDEXNOW_KEY` to Railway env vars
   - Generate key at https://www.indexnow.org/

---

## Quick Reference

| Command | What it does |
|---|---|
| `railway login` | Authenticate with Railway |
| `railway up` | Deploy latest code |
| `railway logs` | View live logs |
| `railway run <command>` | Run a command on Railway |
| `railway open` | Open your app in browser |
| `railway status` | Check deployment status |

| URL | What it shows |
|---|---|
| `/` | Homepage with search |
| `/search?q=python` | Job search results |
| `/jobs/{uuid}` | Job detail with JSON-LD |
| `/employers` | Employer directory |
| `/docs` | Interactive API docs |
| `/api/v1/stats` | Index statistics |
| `/api/v1/jobs/search?q=engineer&country=US` | API search |
| `/llms.txt` | AI discovery file |
| `/sitemap.xml` | Sitemap for search engines |

---

## Troubleshooting

**"No module named src"** — Make sure you're running commands with `railway run` not locally.

**Database connection failed** — Check that `DATABASE_URL_SYNC` uses `postgresql://` (not `postgresql+asyncpg://`).

**0 jobs after crawl** — The quick crawl doesn't need a database. If using `--greenhouse`, make sure you ran `discover_greenhouse` first.

**Railway build fails** — Check that `requirements.txt` doesn't have `mcp` (needs Python 3.10+). Railway uses Python 3.9 by default. Add a `runtime.txt` with `python-3.11.0` to fix.

To force Python 3.11 on Railway, create:
```bash
echo "3.11.0" > runtime.txt
```
Then redeploy: `railway up`
