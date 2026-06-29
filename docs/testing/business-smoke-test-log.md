# NamEngine Business Smoke Test Log

## 2026-06-29 - Five-round Business smoke after context-first intake update

Raw backup CSVs:

- `namengine_business_smoke_test_20260629-080650.csv`
- `namengine_business_smoke_test_20260629-080652.csv`
- `namengine_business_smoke_test_20260629-080654.csv`
- `namengine_business_smoke_test_20260629-080657.csv`
- `namengine_business_smoke_test_20260629-080658.csv`

Scope:

- Five full smoke batches.
- 7 cases per batch: 5 curated Business cases and 2 Original Business cases.
- 250 generated rows total: 200 curated rows and 50 original rows.
- Cases covered local service, SaaS/app, creative studio, nonprofit, newsletter/media, product, and studio original naming.

Environment:

- Local run on 2026-06-29 after commits `694578f`, `91ae618`, `527355a`, `fba2f44`, and `62bbd01`.
- Curated path used `fallback` for all 200 curated rows.
- Original rows were marked `openai_or_fallback_original`; the identical outputs across all five runs indicate fallback behavior.

Findings:

- Routing/storage passed: each run completed and wrote a 50-row CSV.
- The new Business intake fields did not break generation or CSV capture.
- Fallback curated names are functional but too repetitive for real quality judgment. Every curated case reused the same 8-name pool: `Asterly`, `Verda`, `Signal & Co.`, `Northline`, `Cedar House`, `Blueforge`, `Keystone Works`, and `Foundry Lane`.
- Curated fallback ranking shifted slightly between rounds, but the candidate pool did not adapt enough to different briefs. SaaS, nonprofit, local service, and newsletter/media all received the same names.
- Best fallback names: `Northline`, `Blueforge`, `Signal & Co.`, `Keystone Works`, `Foundry Lane`.
- Weak or over-broad fallback names: `Asterly` and `Verda` are brandable but too generic across unrelated business cases; `Cedar House` fits local/studio contexts but not SaaS/newsletter.
- Original product fallback repeated the same five names every round: `Modon`, `Keenara`, `Veralo`, `Trovesa`, `Modoa`. These are mostly usable shapes, though `Modoa` feels weak.
- Original studio fallback repeated `Cedarly`, `Asteren`, `Cedaror`, `Northar`, and `Morrowve`. `Asteren` is the strongest; `Cedaror` and `Morrowve` feel awkward and should be avoided.

Recommended next actions:

- Do not judge Business name quality from these fallback-only runs.
- Run the same five-round smoke with OpenAI configured before evaluating the new context-first Business prompt.
- Improve fallback diversity only if fallback quality matters for the deployed experience without API access.

## 2026-06-28 - Early Business lane smoke test

Raw backup CSVs:

- `namengine_business_smoke_test_20260628-203340.csv`
- `namengine_business_smoke_test_20260628-203427.csv`

Scope:

- Curated and original Business naming paths.
- Project types tested: local service, app/software, studio/agency, nonprofit, newsletter/media, product.
- Sortable labels: `BUS001`-`BUS007`, `Business Curated`, `Business Original`.

Environment:

- Local prototype, no Business Render deployment yet.
- Local Business app does not currently have an OpenAI API key configured, so curated smoke tests used fallback names.
- Route/static checks passed for homepage, original intake, results POSTs, logo image, and share image.

Findings:

- Curated fallback is functional but repetitive across project types. This is acceptable as a no-key fallback, but final quality should be judged with OpenAI configured.
- The fallback curated set contains several plausible Business names: `Northline`, `Blueforge`, `Signal & Co.`, `Cedar House`, `Asterly`, `Foundry Lane`, `Verda`, `Keystone Works`.
- Original product fallback was directionally acceptable: `Modon`, `Keena`, `Verasa`, `Novily`, `Veron`.
- First original studio fallback produced awkward stitched names such as `Daworks` and `Foundryi`.

Action taken:

- Tightened Business original fallback construction for studio/agency prompts by removing literal suffix stitching such as `works`, `house`, and `studio` from generated single-word fallback candidates.
- Second smoke improved the studio originals to cleaner shapes such as `Bluely`, `Northon`, `Bluera`, `Toron`, and `Asteren`.

Recommended before deploy:

- Configure OpenAI locally or in the first Render preview and rerun smoke against the real model path.
- Keep CSVs as backup only; summarize findings here after each smoke round.
- Do not evaluate final Business-name quality from fallback-only curated output.
