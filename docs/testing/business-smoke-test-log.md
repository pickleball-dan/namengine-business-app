# NamEngine Business Smoke Test Log

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
