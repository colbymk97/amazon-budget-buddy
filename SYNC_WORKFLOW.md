# Amazon Budget Buddy — Workflow & Roadmap Notes

---

## Current Sync Workflow (CLI)

Run these two commands whenever you want to pull in new Amazon charges and annotate them in Actual Budget.

### Step 1: Collect latest Amazon orders

```bash
python3 -m amazon_spending collect --retailer amazon --stop-on-known --headed
```

- `--stop-on-known` stops as soon as it hits an already-imported order (fast incremental)
- `--headed` is required — Amazon blocks headless browsers; a Chrome window will open
- Session cookies are reused after the first login, so MFA is usually only needed once

### Step 2: Sync to Actual Budget

```bash
python3 -m amazon_spending actual-sync --verbose
```

- Matches each charge to an Actual transaction by exact amount within ±3 days
- Appends the Amazon order ID and line items to that transaction's `notes` field
- Already-synced transactions are automatically skipped

### Preview before committing

```bash
python3 -m amazon_spending actual-sync --dry-run --verbose
```

---

## Troubleshooting

**"no match" transactions** — the charge exists in Amazon but not yet in Actual. Your bank/card feed in Actual hasn't caught up. Re-run `actual-sync` after Actual imports those transactions.

**Headless mode fails** — always use `--headed` for Amazon.

**`actualpy` not installed** — `pip3 install actualpy`, then retry.

**Update Actual config:**
```bash
python3 -m amazon_spending actual-configure --base-url http://localhost:5006 --file "My Finances"
```

---

## What's Already Built

More exists than it might seem. Here's the current state:

| Area | Status |
|------|--------|
| Amazon scraper (Playwright) | Working |
| SQLite data store | Working |
| FastAPI backend | Working |
| React frontend (7 pages) | Working |
| Actual Budget sync (CLI) | Working |
| Actual Budget sync (UI) | **API exists, no UI yet** |
| Budget categories (create) | Working in Admin page |
| Budget categories (assign to txns) | **API exists, no UI yet** |
| Auto-categorization | **Not started** |

The backend is further ahead than the frontend — the endpoints for Actual sync (`POST /actual/sync`) and category assignment (`PATCH /transactions/:id/budget`) are already written and tested. The React side just hasn't wired them up yet.

---

## Thoughts: What To Build Next

### 1. Actual Budget sync in the UI

The `POST /actual/sync` and `GET /actual/status` endpoints already exist. The UI needs:

- A status card on the Home page showing pending count and configured account
- A "Sync to Actual" button (similar to the existing "Import New Data" button)
- Progress/result display: X synced, Y no match

This is a small amount of frontend work — maybe a few hours — and would eliminate the need to run CLI commands at all.

### 2. Transaction categorization UI

The backend fully supports categories and the `assignTransactionBudget` API function is already defined in `api.ts` — just never called. The frontend needs:

- A dropdown or modal on the TransactionDetailPage to pick category + subcategory
- Possibly a bulk-assign view on the TransactionsPage (select multiple, assign all)

### 3. Auto-categorization

This is the most impactful feature for reducing manual work. A few approaches, roughly ordered by effort:

**Rule-based (low effort, good enough):** Match item titles and order labels against keyword patterns you define. E.g., "diapers" → Household > Baby. Easy to build, easy to audit, fully offline, and open-source friendly (no API keys needed). Good starting point.

**AI-assisted (medium effort, more powerful):** Send item titles + amounts to a Claude/OpenAI call and ask it to suggest a category from your defined list. The tricky part for open source is that users would need their own API key — but that's a reasonable ask and a common pattern. Could be optional/pluggable.

**Learned from history (longer term):** Once enough transactions are manually categorized, train a simple classifier (e.g. sklearn TF-IDF + logistic regression) on item titles. Fully offline, no API keys, improves over time. Probably overkill until there's a meaningful corpus of labeled data.

The cleanest open-source approach is probably: **rule-based as the default, AI-assisted as an optional plugin** with a user-supplied API key.

### 4. Open-source considerations

A few things worth thinking through before publishing:

**Remove personal data from the repo:** The `data/` directory (raw HTML snapshots, the SQLite DB) must be in `.gitignore`. Check that no order IDs, names, or addresses are hardcoded anywhere.

**The Actual Budget integration is a differentiator.** Most Amazon-scraping tools don't sync to Actual — this is a genuine gap in the ecosystem. Worth highlighting prominently.

**Browser session / auth story:** The biggest friction point for new users will be getting Amazon auth working. The `--headed` fallback helps, but documenting this clearly (and ideally detecting MFA gracefully) is important for first-run experience.

**Config management:** Right now Actual credentials are stored in the SQLite DB. For open source, a `config.toml` or `.env` file approach might feel more familiar to users and be easier to document.

**The name:** "amazon-spending" is functional but generic. A more distinctive name could help with discoverability if this goes on GitHub.

---

## Rough Priority Order

1. **Actual sync button in UI** — small effort, eliminates CLI dependency entirely
2. **Category assignment UI on TransactionDetailPage** — the backend is ready
3. **Rule-based auto-categorization** — biggest quality-of-life improvement
4. **Open-source prep** — gitignore audit, config story, README polish
5. **AI-assisted categorization** — optional, additive
