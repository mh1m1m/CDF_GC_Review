# Visual intelligence dependency assessment — 2026-10-24

Baseline: PR 7, 00c4f5b. Python/FastAPI, SQLite, React 18 and Vite are retained. Versions below were resolved from installed metadata or package registries; DEFER means no version is added or claimed validated. No migration to a new agent framework or database is required for this bounded local pilot.

| Technology | Existing → proposed | Purpose / decision | License | Compatibility, security, build and performance |
|---|---|---|---|---|
| React / React DOM | ^18.3.1 → 18.3.1 | INSTALL exact pin; existing UI | MIT | Retain contracts; no React major migration |
| Vite | ^6.1.0 → 8.3.5 | INSTALL current stable build tool | MIT | Node >=22.12; build/browser verification required; dev server stays loopback |
| TypeScript | ^5.7.3 → 5.9.3 | INSTALL exact compatible compiler | Apache-2.0 | Static checks, no runtime cost |
| Apache ECharts | absent → 6.1.0 | INSTALL gauges/heatmaps/distributions | Apache-2.0 | Modular SVG renderer, resize/disposal; no HTML tooltips; chart text alternatives; lazy chunk |
| React Flow | absent → 12.12.0 | INSTALL debate/evidence navigation | MIT | React18 peer support; bounded nodes, keyboard details; no executable node content |
| Lucide React | absent → 1.61.0 | INSTALL semantic icon primitives | ISC | Tree-shaken icons inside proposed glass treatments; not official logo artwork |
| Prettier | absent → 3.9.10 | INSTALL transient development formatting tool | MIT | Exact npm-exec version; no production bundle or runtime service |
| Vitest | absent → 5.0.5 | INSTALL frontend contract tests | MIT | Node >=22.12, Vite8 compatible; development only |
| Playwright | ^1.57.0 → 1.64.1 | INSTALL browser/screenshots | Apache-2.0 | Desktop/mobile Chromium, synthetic credentials only, reduced-motion tests |
| axe-core Playwright | absent → 4.14.0 | INSTALL accessibility checks | MPL-2.0 | Development only; browser scan adds seconds, not production code |
| FastAPI / Uvicorn / HTTPX | >=0.115,<1 / >=0.34,<1 / optional >=0.27,<1 → 0.162.0 / 0.54.0 / 0.28.1 | INSTALL exact tested API/client versions | MIT / BSD-3-Clause / BSD-3-Clause | Matches the stable-container acceptance environment; loopback restrictions retained; removes direct version drift |
| Pydantic | 2.13.4 transitive → 2.13.4 direct | INSTALL bounded read-model contracts | MIT | Existing FastAPI2-compatible validation; forbid extra data; never approval authority |
| OpenTelemetry API | 1.45.1 transitive → 1.45.1 direct | INSTALL local projection spans | Apache-2.0 | No SDK/exporter endpoint by default; allowlisted boolean/count attributes only; no prompts, names or evidence text |
| Hypothesis | absent → 6.170.9 | INSTALL metric invariant tests | MPL-2.0 | Test-only; bounded examples; unknown/zero denominators |
| Bandit | absent → 1.9.4 | INSTALL static security scan | Apache-2.0 | Test-only; report scope and limitations rather than suppressing findings |
| pip-audit | absent → 2.10.1 | INSTALL dependency scan | Apache-2.0 | Network advisory access required; blocked advisory access is not a clean scan |
| LangGraph | absent → not selected | DEFER orchestration/checkpoints | MIT | Existing orchestrator owns cycles/roles; adding runtime risks duplicate authority and persistence |
| Instructor | absent → not selected | DEFER output retries | MIT | Existing schema/retry guards authoritative; no measured gap |
| NetworkX | 3.7 transitive → no direct pin | DEFER argument analytics | BSD-3-Clause | Simple evidence-edge projections need no graph engine; avoid unnecessary traversal cost |
| RapidFuzz | absent → not selected | DEFER duplicate detection | MIT | Existing deterministic semantic duplicate rules preserved; change needs independent evaluation |
| Ragas | absent → not selected | DEFER grounded evaluation | Apache-2.0 | Requires independent labels/authorized provider; model scores cannot populate invented gauges |
| DeepEval | absent → not selected | DEFER quality evaluation | Apache-2.0 | Same label/provider dependency; avoid unapproved external transmissions |
| Recharts | absent → not selected | REJECT duplicate chart runtime | MIT | ECharts covers selected charts; avoid redundant bundle |
| TanStack Table | absent → not selected | DEFER large-table virtualization | MIT | Current case tables are small and native accessible tables suffice; assess paging with measured volume |
| shadcn/ui | absent → not selected | DEFER component generator | MIT | Preserve existing form contracts; no full component-framework migration justified |
| Tailwind CSS | absent → not selected | DEFER CSS compiler | MIT | Shared CSS properties already support design tokens; no second styling pipeline |
| Framer Motion | absent → not selected | DEFER motion runtime | MIT | CSS reduced-motion transitions suffice; no artificial agent activity |
| PostgreSQL | absent → not selected | DEFER multi-user storage | PostgreSQL | No institutional deployment/concurrency requirement supplied; migrations/backups need design |
| SQLAlchemy / Alembic | absent → not selected | DEFER ORM/migrations | MIT | Existing SQLite store is adequate; avoid duplicate persistence |
| Redis | absent → not selected | DEFER queues/cache | Version-dependent (AGPL/RSAL/SSPL choices) | No server/license deployment selected; extra service not justified |
| pgvector | absent → not selected | DEFER vector search | PostgreSQL | No approved embedding corpus/provider; confidential derivatives stay private |
| LibreOffice | 25.2.3.2 container → retain | INSTALL retained stable path | MPL-2.0/LGPL-3.0+ components | Independent recalculation/PDF validation; host alpha not used for acceptance |
| python-docx | 1.2.0 → retain | INSTALL retained editable Word | MIT | Existing native document/comment engines preserved; draft export marked |
| lxml | 6.1.3 → retain | INSTALL retained OOXML | BSD-3-Clause | Reject external entities/untrusted archives; no remote references |
| PyMuPDF | 2.0 → retain | INSTALL retained private PDF extraction | AGPL-3.0/commercial | Existing dependency; deployment/license assessment remains necessary; no private pages in public artifacts |
| Pillow | 12.3.0 → 13.0.0 | INSTALL security update after advisory scan | HPND | Regression-test existing renderers and draft gauge artwork |
| pypdf | 6.17.0 → 6.21.2 | INSTALL security update after advisory scan | BSD-3-Clause | PDF parsing regression checks; existing pins had reported vulnerabilities |
| openpyxl | 3.1.5 → retain | INSTALL retained native Excel | MIT | Native charts/formulas, source-linked data; formula injection escaped as text |
| XlsxWriter | absent → not selected | REJECT duplicate exporter | BSD-2-Clause | openpyxl already creates native charts and formulas |
| pytest | 9.1.1 → retain | INSTALL retained regression runner | MIT | Core + new intelligence/export/security cases |
| Gitleaks | absent → not selected | DEFER dedicated binary | MIT | Existing tracked-file guard plus Bandit/dependency scans used now; no claim of exhaustive secret-history audit |

Runtime additions are limited to three visual libraries and already-compatible Python contracts/telemetry. Test tooling stays out of browser production bundles. Exact direct versions and resolved JS transitives are committed in package.json/package-lock.json. New Python pins are in requirements-visual.txt and requirements-security.txt. Audit results and measured build/browser evidence are recorded in the handoff; no dependency's presence proves institutional readiness.
