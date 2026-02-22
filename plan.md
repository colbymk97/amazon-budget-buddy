flowchart TD
    A[Amazon Spending Reconciler<br/>Personal Account] --> B[Goals]
    A --> C[Constraints]
    A --> D[Architecture]
    A --> E[Execution Phases]
    A --> F[Matching Strategy]
    A --> G[Data Model]
    A --> H[Risk Controls]
    A --> I[Deliverables]

    B --> B1[Per-transaction report by date range or order limit]
    B --> B2[Link card/bank transaction -> Amazon order -> line items]
    B --> B3[Handle split charges across shipments]
    B --> B4[Export clean CSV for Copilot recategorization workflow]
    B --> B5[Flag essential vs nonessential]

    C --> C1[No official personal buyer API]
    C --> C2[Must support MFA and occasional captcha/manual intervention]
    C --> C3[Scraping fragility expected; design retry + resume]
    C --> C4[Local-first, user-controlled data storage]

    D --> D1[Collector Layer]
    D --> D2[Normalizer Layer]
    D --> D3[Matcher Layer]
    D --> D4[Review Layer]
    D --> D5[Exporter Layer]

    D1 --> D1a[Amazon Collector: Playwright login + orders + order detail pages]
    D1 --> D1b[Finance Collector: Copilot/Bank CSV import]

    D2 --> D2a[Canonical schema across orders, shipments, items, transactions]
    D2 --> D2b[Currency normalization + timezone normalization]

    D3 --> D3a[Deterministic exact matching rules]
    D3 --> D3b[Scored candidate ranking for ambiguous cases]
    D3 --> D3c[Proportional fallback allocator]

    D4 --> D4a[Review queue for low-confidence matches]
    D4 --> D4b[Manual override table + audit trail]

    D5 --> D5a[transaction_item_report.csv]
    D5 --> D5b[monthly_essential_vs_nonessential.csv]
    D5 --> D5c[unmatched_transactions.csv]

    F --> F1[Step 1: Shipment-level exact amount match]
    F --> F2[Step 2: Order-level exact amount match]
    F --> F3[Step 3: Date-window candidate scoring]
    F --> F4[Step 4: Proportional line-item allocation]
    F --> F5[Step 5: Manual review if confidence below threshold]

    F1 --> F1a[amount_diff == 0 and date_delta <= 3 days]
    F3 --> F3a[score = amount_similarity + date_similarity + residual_balance_fit]
    F4 --> F4a[Allocate by item subtotal weights among remaining unmatched items]
    F5 --> F5a[confidence < 0.80 -> review_queue]

    G --> G1[orders]
    G --> G2[shipments]
    G --> G3[order_items]
    G --> G4[transactions]
    G --> G5[matches]
    G --> G6[manual_overrides]

    G1 --> G1a[order_id, order_date, total, tax, shipping, payment_last4]
    G2 --> G2a[shipment_id, order_id, ship_date, shipment_total]
    G3 --> G3a[item_id, order_id, title, qty, item_subtotal, item_tax]
    G4 --> G4a[txn_id, posted_date, amount, merchant_raw, account_id]
    G5 --> G5a[txn_id, order_id/shipment_id, item_id, allocated_amount, confidence, method]
    G6 --> G6a[override_id, target_txn_id, selected_order_or_item, reason, created_at]

    E --> P0[Phase 0: Repo bootstrap]
    E --> P1[Phase 1: Ingestion MVP]
    E --> P2[Phase 2: Matching engine]
    E --> P3[Phase 3: Review + overrides]
    E --> P4[Phase 4: Essential labeling]
    E --> P5[Phase 5: Hardening and automation]

    P0 --> P0a[Set up Python project + CLI + SQLite]
    P0 --> P0b[Add sample fixtures and smoke tests]

    P1 --> P1a[Import bank/Copilot transactions CSV]
    P1 --> P1b[Manual Amazon order CSV/json import (bootstrap path)]
    P1 --> P1c[Generate first unmatched report]

    P2 --> P2a[Implement 5-step matching pipeline]
    P2 --> P2b[Compute confidence and match_method]
    P2 --> P2c[Persist allocations and residuals]

    P3 --> P3a[CLI review commands: list/apply overrides]
    P3 --> P3b[Regenerate reports with overrides applied]

    P4 --> P4a[Rule-based essential classifier (keywords + curated list)]
    P4 --> P4b[Allow household-specific override tags]
    P4 --> P4c[Emit monthly essential/nonessential summaries]

    P5 --> P5a[Playwright Amazon collector with resume checkpoints]
    P5 --> P5b[Idempotent reruns + dedupe keys]
    P5 --> P5c[Regression tests against real anonymized samples]

    H --> H1[Secrets handling]
    H --> H2[Operational safety]
    H --> H3[Data quality checks]

    H1 --> H1a[No credentials stored in repo; use keychain/env only]
    H2 --> H2a[Rate limiting + random jitter + exponential backoff]
    H2 --> H2b[Checkpoint each page/order for safe restart]
    H3 --> H3a[Validate totals: sum(item allocations) == transaction amount]
    H3 --> H3b[Detect duplicate imports by stable hash keys]

    I --> I1[CLI commands]
    I --> I2[Core outputs]
    I --> I3[Definition of done]

    I1 --> I1a[collect-amazon]
    I1 --> I1b[import-transactions]
    I1 --> I1c[match]
    I1 --> I1d[review]
    I1 --> I1e[export]

    I2 --> I2a[report_transaction_itemized.csv]
    I2 --> I2b[report_unmatched.csv]
    I2 --> I2c[report_monthly_summary.csv]

    I3 --> I3a[>=95% transaction coverage for selected period]
    I3 --> I3b[All low-confidence items present in review queue]
    I3 --> I3c[Re-runs produce stable deterministic outputs]
