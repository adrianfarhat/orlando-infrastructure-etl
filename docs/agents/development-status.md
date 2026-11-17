# Development Status

> Derived from [task-board.md](task-board.md) (source of truth). Updated in the
> same edit as any status change. Last updated: 2026-11-17.

This page is a dashboard view of the board. If it disagrees with the board, the
board wins; fix this page. Acceptance criteria and full verification results live
only on the board, and this page links to them.

## 1. Status at a glance

| Status | Tasks | Count |
|---|---|---|
| Done | T-51 | 1 |
| In progress | T-50 (waiting for user approval of one live read-only run) | 1 |
| Not started, waiting on a pending decision | T-20, T-23, T-43, T-53, T-54, T-55, T-56, T-58, T-70 | 9 |
| Not started, no decision needed | T-01, T-02, T-03, T-04, T-10, T-11, T-12, T-21, T-22, T-24, T-40, T-41, T-42, T-52, T-57, T-59, T-60, T-61 (D-1 pending; proceeds with per-change user approval, as T-50/T-51), T-90 | 19 |
| Blocked | none | 0 |
| **Total** | | **30** |

"Waiting on a pending decision" is a view on this page, not a board status. On
the board these tasks are `Not started` and depend on one of D-1 to D-10.

### By owner

| Owner | Done | In progress | Not started | Total |
|---|---|---|---|---|
| main conversation (user approval) | 1 (T-51) | 1 (T-50) | 6 (T-04, T-53, T-55, T-58, T-59, T-61) | 8 |
| integration-qa | 0 | 0 | 5 (T-01, T-02, T-03, T-70, T-90) | 5 |
| backend | 0 | 0 | 5 (T-10, T-11, T-12, T-21, T-24) | 5 |
| frontend | 0 | 0 | 6 (T-22, T-23, T-40, T-41, T-42, T-43) | 6 |
| data-gis | 0 | 0 | 4 (T-52, T-54, T-56, T-57) | 4 |
| technical-lead | 0 | 0 | 2 (T-20, T-60) | 2 |

T-54 is shared: data-gis does the check, then technical-lead updates the docs.
T-56 and T-57 are proposed by data-gis and applied by the user. Each is counted
once, under its first owner.

## 2. Tasks by wave

Colour key: **green** Done · **blue** In progress · **grey** Not started ·
**amber** Not started and waiting on a decision · **red hexagon** pending decision
· dotted box: a task from an earlier wave. Arrows point from a prerequisite to the
task that needs it. Every wave ends with the T-90 verification gate.

### Wave 0: safety and baseline

```mermaid
flowchart LR
  D1{{"D-1"}}
  subgraph W0["Wave 0"]
    T50["T-50 test_connection<br/>read-only session"]
    T51["T-51 wastewater<br/>dry-run default"]
    T61["T-61 streets + manholes<br/>dry-run default"]
    T01["T-01 baseline<br/>verification"]
    T02["T-02 confirm<br/>F-01 / F-08"]
    T03["T-03 lint<br/>warning source"]
  end
  G0["T-90 gate"]
  D1 -.-> T50
  D1 -.-> T51
  D1 -.-> T61
  T50 -->|"then"| T51
  T51 -->|"then"| T61
  W0 --> G0

  classDef done fill:#bbf7d0,stroke:#15803d,color:#14532d
  classDef progress fill:#bfdbfe,stroke:#1d4ed8,color:#1e3a8a
  classDef todo fill:#e5e7eb,stroke:#6b7280,color:#111827
  classDef decision fill:#fecaca,stroke:#b91c1c,color:#7f1d1d
  class T51 done
  class T50 progress
  class T01,T02,T03,T61,G0 todo
  class D1 decision
```

T-50 and T-51 were applied by the main conversation with user approval, while D-1
is still formally pending.

### Wave 1: fixes with no contract change

```mermaid
flowchart LR
  T01p["T-01"]
  D2{{"D-2"}}
  D3{{"D-3"}}
  subgraph W1["Wave 1"]
    T10["T-10 features<br/>input validation"]
    T11["T-11 db.ts<br/>hardening"]
    T12["T-12 error<br/>logging"]
    T40["T-40 map<br/>resilience"]
    T41["T-41 dashboard<br/>UX"]
    T42["T-42 a11y, dark mode,<br/>responsive"]
    T52["T-52 read-only<br/>DB audit"]
    T20["T-20 features<br/>contract v2"]
  end
  G1["T-90 gate"]
  T01p --> T10
  T01p --> T11
  T01p --> T40
  T01p --> T41
  T10 --> T12
  T40 --> T42
  T41 --> T42
  D2 -.-> T20
  D3 -.-> T20
  W1 --> G1

  classDef todo fill:#e5e7eb,stroke:#6b7280,color:#111827
  classDef waiting fill:#fde68a,stroke:#b45309,color:#78350f
  classDef decision fill:#fecaca,stroke:#b91c1c,color:#7f1d1d
  classDef prior fill:#ffffff,stroke:#9ca3af,stroke-dasharray:4 3,color:#374151
  class T10,T11,T12,T40,T41,T42,T52,G1 todo
  class T20 waiting
  class D2,D3 decision
  class T01p prior
```

### Wave 2: contract v2

```mermaid
flowchart LR
  T20p["T-20"]
  T10p["T-10"]
  T12p["T-12"]
  T40p["T-40"]
  T52p["T-52"]
  D6{{"D-6"}}
  D8{{"D-8"}}
  subgraph W2["Wave 2"]
    T21["T-21 backend<br/>features v2"]
    T22["T-22 frontend<br/>contract adaptation"]
    T53["T-53 road_segments<br/>DDL file"]
    T54["T-54 manholes<br/>provenance"]
    T57["T-57 read-only<br/>DB role"]
  end
  G2["T-90 gate"]
  T20p --> T21
  T10p --> T21
  T12p --> T21
  T21 --> T22
  T40p --> T22
  T52p --> T53
  D8 -.-> T53
  D6 -.-> T54
  T52p --> T57
  W2 --> G2

  classDef todo fill:#e5e7eb,stroke:#6b7280,color:#111827
  classDef waiting fill:#fde68a,stroke:#b45309,color:#78350f
  classDef decision fill:#fecaca,stroke:#b91c1c,color:#7f1d1d
  classDef prior fill:#ffffff,stroke:#9ca3af,stroke-dasharray:4 3,color:#374151
  class T21,T22,T57,G2 todo
  class T53,T54 waiting
  class D6,D8 decision
  class T20p,T10p,T12p,T40p,T52p prior
```

### Wave 3: features and hygiene

```mermaid
flowchart LR
  T01p["T-01"]
  T02p["T-02"]
  T03p["T-03"]
  T21p["T-21"]
  T22p["T-22"]
  T51p["T-51"]
  T52p["T-52"]
  T61p["T-61"]
  D3{{"D-3"}}
  D4{{"D-4"}}
  D5{{"D-5"}}
  D10{{"D-10"}}
  subgraph W3["Wave 3"]
    T23["T-23 asset<br/>inspector"]
    T24["T-24 stats<br/>caching"]
    T55["T-55 loader<br/>consistency"]
    T59["T-59 requirements.txt"]
    T04["T-04 CLAUDE.md +<br/>lint config"]
    T43["T-43 metadata,<br/>home page"]
    T70["T-70 test<br/>harness plan"]
  end
  G3["T-90 gate"]
  T21p --> T23
  T22p --> T23
  D3 -.-> T23
  T21p --> T24
  T51p --> T55
  T52p --> T55
  T61p --> T55
  D4 -.-> T55
  T02p --> T04
  T03p --> T04
  D5 -.-> T43
  T01p --> T70
  D10 -.-> T70
  W3 --> G3

  classDef todo fill:#e5e7eb,stroke:#6b7280,color:#111827
  classDef waiting fill:#fde68a,stroke:#b45309,color:#78350f
  classDef decision fill:#fecaca,stroke:#b91c1c,color:#7f1d1d
  classDef prior fill:#ffffff,stroke:#9ca3af,stroke-dasharray:4 3,color:#374151
  class T24,T59,T04,G3 todo
  class T23,T55,T43,T70 waiting
  class D3,D4,D5,D10 decision
  class T01p,T02p,T03p,T21p,T22p,T51p,T52p,T61p prior
```

### Wave 4: needs approval or architecture work

```mermaid
flowchart LR
  T52p["T-52"]
  T57p["T-57"]
  D7{{"D-7"}}
  D9{{"D-9"}}
  subgraph W4["Wave 4"]
    T56["T-56 schema<br/>migrations"]
    T58["T-58 one place for<br/>DATABASE_URL"]
    T60["T-60 demo schema +<br/>IoT design"]
  end
  G4["T-90 gate"]
  T52p --> T56
  D9 -.-> T56
  T57p --> T58
  D7 -.-> T58
  T52p --> T60
  W4 --> G4

  classDef todo fill:#e5e7eb,stroke:#6b7280,color:#111827
  classDef waiting fill:#fde68a,stroke:#b45309,color:#78350f
  classDef decision fill:#fecaca,stroke:#b91c1c,color:#7f1d1d
  classDef prior fill:#ffffff,stroke:#9ca3af,stroke-dasharray:4 3,color:#374151
  class T60,G4 todo
  class T56,T58 waiting
  class D7,D9 decision
  class T52p,T57p prior
```

## 3. Blockers and pending decisions

All ten decisions are **PENDING**. Options and recommendations are on the
[task board](task-board.md#decisions).

| Item | What it is | What it blocks |
|---|---|---|
| D-1 | Who edits `database/` and `extractors/` | Formally T-50 and T-51, which went ahead with per-change user approval. T-61 also depends on D-1. Becomes critical for the product vision, where most new work is SQL and data. |
| D-2 | `/features` limits (bbox cap, order, rounding) | T-20 → T-21 → T-22, T-23 |
| D-3 | Asset inspector data shape | T-20, T-23 |
| D-4 | Loader policy (null geometry, DDL) | T-55, and the DDL item deferred from T-51 |
| D-5 | What `/` shows | T-43 |
| D-6 | ArcGIS metadata GET | T-54 |
| D-7 | Where `DATABASE_URL` lives | T-58 |
| D-8 | Path of the DDL file | T-53 |
| D-9 | Whether to do schema migrations | T-56 |
| D-10 | Test runner | T-70 |
| User approval | One live read-only Neon run of `database/test_connection.py` | Closing T-50 |
| Environment | T-01 needs a running dev server (the user may need to start it) | T-01, and through it T-10, T-11, T-40, T-41, T-70 |

## 4. Latest verification results

| Date | Task | Result | Details |
|---|---|---|---|
| 2026-11-16 | T-51 | **Done.** All checks pass with no Neon access. | [Task board → T-51](task-board.md#t-51-wastewater-loader-writes-nothing-by-default-p0) |
| 2026-11-16 | T-50 | Code checks pass; the live read-only run is pending approval | [Task board → T-50](task-board.md#t-50-test_connectionpy-read-only-session-p0) |
| 2026-11-16 | none (team inspection) | Run by integration-qa during the inspection, not yet recorded against a task: `tsc --noEmit` passes; lint 0 errors / 1,103 warnings, cause unknown (`.next/**` is already ignored). T-01 and T-03 will re-run and record. | [Task board findings](task-board.md#findings-from-the-2026-11-16-repository-inspection) |

## 5. How work flows through the team

```mermaid
flowchart TD
  U(["User"]) -->|"request"| MC["Main conversation<br/>(coordinator)"]
  MC -->|"asks for a plan"| TL["technical-lead<br/>writes tasks: owner, scope,<br/>acceptance, dependencies"]
  TL -->|"proposed tasks"| G1{{"Gate: user approves<br/>the plan / board"}}
  G1 --> MC
  MC -->|"dispatch one task<br/>to one owner"| OW["Owner implements<br/>(backend / frontend / data-gis /<br/>main conversation for unowned files)"]
  OW --> G2{{"Gate: user approval needed?<br/>DB write, migration, ETL run,<br/>dependency, config, env, push"}}
  G2 -->|"approved or not needed"| QA["integration-qa verifies<br/>(read-only checks)"]
  QA -->|"results"| MC
  MC -->|"records results"| BOARD[("task-board.md<br/>+ this page")]
  BOARD -->|"review"| TL
  QA -->|"fails"| OW
```

- Only the owner of a file edits it, and only one task edits a file at a time
  (CLAUDE.md, *Agents and file ownership*).
- A task is `Done` only when its verification results are recorded on the board
  (CLAUDE.md, rule 10).
