# ZammeJobs Go-To-Market Plan

## The Wedge

ZammeJobs is the **only job board that wants to be scraped by AI** while Indeed and LinkedIn block them. That's the story.

Three audiences, one narrative:

1. **Job seekers** — "Find jobs in ChatGPT, Claude, and Perplexity, not on LinkedIn."
2. **AI labs** — "The open, CC-BY jobs corpus. JSON-LD. Hugging Face mirror. Take it."
3. **Employers / ATS** — "Get your jobs indexed by every AI engine, not just Google."

Launch hook: *"We open-sourced the jobs corpus the AI search era needs — Indeed sued Anthropic, we're shipping them training data."*

---

## Agent Team — 18 agents, 5 squads

### Squad 1 — Strategy & Voice
Run first. Everything else depends on these.

| Agent | Scope |
|---|---|
| `brand-strategist` | Master narrative, ICPs, messaging matrix, taglines, banned phrases |
| `founder-voice` | Rick's first-person POV doc — tone, anecdotes, recurring themes |
| `pr-narrative-architect` | The 3 launch stories: open corpus, AI-first search, anti-LinkedIn |

### Squad 2 — Channel Writers (parallel content production)

| Agent | Scope |
|---|---|
| `linkedin-writer` | 5x/week founder posts + 2x/week thought leadership |
| `x-twitter-writer` | Daily threads, AI-jobs commentary, build-in-public stats |
| `reddit-strategist` | Value-first comments in r/jobs, r/cscareerquestions, r/recruiting, r/MachineLearning, r/SideProject |
| `tiktok-shorts-writer` | 30–60s scripts: "I asked ChatGPT to find me a job" |
| `youtube-longform-writer` | 8–15min explainers + founder vlogs |
| `blog-writer` | zammejobs.com/blog + Dev.to + Hashnode + Medium cross-posts |
| `newsletter-writer` | Weekly Substack "AI + Jobs Index" digest |

### Squad 3 — Launch Detonators (one-shot, high-leverage)

| Agent | Scope |
|---|---|
| `hackernews-launcher` | Show HN post, comment prep, Tue 8am PT timing |
| `producthunt-launcher` | Full PH kit: gallery, first-comment, hunter outreach, ship-day comments |
| `press-release-writer` | TechCrunch, The Information, Axios, Business Insider, HR Brew pitches |
| `podcast-pitcher` | Lenny's, Latent Space, 20VC, Recruiting Future, ChatGPT-focused shows |

### Squad 4 — Distribution & Growth

| Agent | Scope |
|---|---|
| `seo-content-engineer` | Programmatic pages: `/jobs/{role}`, `/jobs/{company}`, `/remote/{country}` |
| `influencer-outreach` | Recruiter LinkedIn voices, AI Twitter, careers TikTokers (target list of 200) |
| `partnerships-bizdev` | VONQ/Broadbean/idibu/eQuest pitches, ATS integration outreach |
| `community-manager` | Discord/Slack (RecOps, MLOps, indie hackers) |

### Squad 5 — Creative & Measurement

| Agent | Scope |
|---|---|
| `visual-designer` | OG images, ad creatives, brand kit, video b-roll briefs |
| `analytics-tracker` | UTM scheme, weekly KPI dashboard, channel attribution |

---

## 30/60/90 Sequence

### Days 1–14 — Foundation
- Strategy squad outputs the message bible
- Visual designer ships brand kit + OG images
- SEO engineer ships programmatic role/company pages
- Newsletter and blog seed 6 posts as a backlog

### Days 15–30 — Coordinated Launch Week
- **Tuesday:** Show HN
- **Wednesday:** Product Hunt
- **Thursday:** press embargo lifts
- Founder-voice does LinkedIn + X long-form same day
- Reddit squad seeds AMAs in 4 subs over the week
- Newsletter goes out Friday

### Days 31–60 — Content Saturation
Daily cadence:
- 5 LinkedIn posts
- 3 X threads
- 1 TikTok
- 1 blog
- 7 Reddit comments

Plus: 200 personalized influencer pitches, 8 podcast bookings, VONQ/Broadbean conversations open.

### Days 61–90 — Compound + Double Down
- Analytics tracker reports channel ROI
- Kill bottom 2 channels, 2x budget on top 2
- YouTube long-form launches
- Begin paid amplification on top 3 organic posts

---

## Automation Split

### Fully Automatable (90–100%, no human in loop) — ~70% of volume

- **SEO programmatic pages** — generate from DB, ship via PR + auto-deploy. Scales to 100K+ pages
- **Blog post drafts** — daily long-form, cross-post to Dev.to/Hashnode/Medium via API
- **X/Twitter threads** — daily, scheduled via Buffer/Typefully API
- **Newsletter** — weekly Substack digest from job ingestion stats + AI news RSS
- **OG image generation** — per-page social cards via Satori/Puppeteer
- **UTM tagging + attribution dashboard** — GA4/Plausible API → weekly Slack KPI post
- **IndexNow / Google Indexing pings** — already built
- **Hugging Face dataset refresh** — already built
- **Reddit/HN/PH monitoring** — agent watches mentions, drafts replies for 1-click send
- **Influencer target list scraping** — pull 200 LinkedIn/X handles, enrich with email
- **Cold outreach drafts** — personalized first-touch emails to ATS partners, podcasts, press

### Human-Required (agent drafts, you approve in <60s) — ~25%, ~30 min/day

- **LinkedIn posts** — LinkedIn API is locked down; agent drafts, you paste
- **TikTok/YouTube videos** — agent writes script + shotlist, you record
- **Podcast appearances** — agent pitches and books, you show up
- **Reddit comments** — agent drafts, you post (Reddit shadowbans automated accounts)
- **Press calls/interviews** — agent prepares briefing doc, you take the call
- **Product Hunt launch day** — agent prewrites every comment reply, you ship

### Human-Only — ~5%

- Founder voice on camera/podcast
- 1:1 DMs with influencers and reporters once they reply
- Strategic pivots based on what's working

---

## Automation Stack

- **Cron + Railway worker** — reuse existing Celery beat for scheduled agent runs
- **APIs needed:** Buffer/Typefully (X), Substack, Dev.to, Hashnode, Medium, GA4, Plausible, Slack webhook, Resend (email), Apify (scraping)
- **Approval queue:** `/admin/queue` page on zammejobs.com where drafts land; mobile swipe approve/reject
- **Anthropic API** — batched calls + prompt-cached system prompts, ~$50–150/mo at this volume
- **Agent definitions** — `~/.claude/agents/zammejobs/` for ad-hoc CLI invocation

---

## Open Questions

1. Public face — Rick solo, or co-founder/team voice?
2. Paid budget envelope (LinkedIn ads, influencer fees, PH hunter)?
3. Channels off-limits (e.g. TikTok)?
