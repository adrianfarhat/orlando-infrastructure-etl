# Task Dependencies and Waves

> **Live status for every task and decision is in
> [GitHub Project #1](https://github.com/users/adrianfarhat/projects/1) (private).** This page
> shows only how tasks depend on each other and which wave they belong to. It does
> not track status. (The filename is kept because other pages link to it.)

Scope, acceptance criteria and verification evidence live on the
[task board](task-board.md). If this page disagrees with the board about a
dependency or a wave, the board wins; fix this page.

## 1. Tasks by wave

Key: **rectangle** = a task in this wave · **dotted rectangle** = a prerequisite
from another wave or from outside the board, such as PR #1 (a dependency, not a
status) · **hexagon** = a decision
(D-x) · solid arrow = task dependency · dotted arrow = depends on a decision.
Arrows point from a prerequisite to the task that needs it. Every wave ends with
the T-90 verification gate. Colours and styles here never show status.

### Wave 0: safety and baseline

```mermaid
flowchart LR
  D1{{"D-1"}}
  PR1["PR #1 baseline<br/>(chore/baseline-safety-and-docs)"]
  subgraph W0["Wave 0"]
    T05["T-05 git/PR workflow<br/>in CLAUDE.md"]
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
  PR1 --> T05
  W0 --> G0

  classDef decision fill:#ffffff,stroke:#374151,color:#111827
  classDef otherwave stroke-dasharray:4 3
  class D1 decision
  class PR1 otherwave
```

T-50, T-51 and T-61 go ahead with per-change user approval under D-1 option (a).

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

  classDef decision fill:#ffffff,stroke:#374151,color:#111827
  classDef otherwave stroke-dasharray:4 3
  class D2,D3 decision
  class T01p otherwave
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

  classDef decision fill:#ffffff,stroke:#374151,color:#111827
  classDef otherwave stroke-dasharray:4 3
  class D6,D8 decision
  class T20p,T10p,T12p,T40p,T52p otherwave
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

  classDef decision fill:#ffffff,stroke:#374151,color:#111827
  classDef otherwave stroke-dasharray:4 3
  class D3,D4,D5,D10 decision
  class T01p,T02p,T03p,T21p,T22p,T51p,T52p,T61p otherwave
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

  classDef decision fill:#ffffff,stroke:#374151,color:#111827
  classDef otherwave stroke-dasharray:4 3
  class D7,D9 decision
  class T52p,T57p otherwave
```

## 2. Documentation synchronization (T-80 to T-89)

Plan approved by the user 2026-11-17. These tasks use the same Wave field as the
rest of the board (waves 1–3); each subgraph below is one wave. Dotted
rectangles are prerequisites from the main waves above. Task details:
[task board](task-board.md#documentation-synchronization-t-80-to-t-89).

```mermaid
flowchart LR
  T05p["T-05"]
  T03p["T-03"]
  T52p["T-52"]
  T59p["T-59"]
  D8{{"D-8"}}
  subgraph DS1["Wave 1"]
    T80["T-80 conventions +<br/>doc map"]
    T89["T-89 status out<br/>of Markdown"]
    T81["T-81 docs check +<br/>link checker"]
    T83["T-83 docs impact<br/>tool"]
    T84["T-84 PR template +<br/>CLAUDE.md docs rules"]
  end
  subgraph DS2["Wave 2"]
    T82["T-82 Mermaid +<br/>conventions lint"]
    T85["T-85 CI docs<br/>workflow"]
  end
  subgraph DS3["Wave 3"]
    T86["T-86 schema baseline<br/>migration"]
    T87["T-87 schema doc<br/>generator"]
    T88["T-88 consolidate<br/>schema docs"]
  end
  T80 --> T81
  T80 --> T83
  T80 --> T82
  T81 --> T82
  T83 --> T84
  T05p -->|"same file: CLAUDE.md"| T84
  T81 --> T85
  T82 --> T85
  T83 --> T85
  T03p --> T85
  T59p --> T85
  T52p --> T86
  D8 -.-> T86
  T86 --> T87
  T85 --> T87
  T87 --> T88

  classDef decision fill:#ffffff,stroke:#374151,color:#111827
  classDef otherwave stroke-dasharray:4 3
  class D8 decision
  class T05p,T03p,T52p,T59p otherwave
```

T-86 overlaps T-53 (the `road_segments` DDL file); whether T-53 is closed as
superseded is the user's decision.

## 3. Decisions and what they block

Options and recommendations are on the [task board](task-board.md#decisions).
Whether a decision is made is shown in
[Project #1](https://github.com/users/adrianfarhat/projects/1) (private).

| Item | What it is | What depends on it |
|---|---|---|
| D-1 | Who edits `database/` and `extractors/` | T-50, T-51 and T-61, which go ahead with per-change user approval under option (a). Becomes critical for the product vision, where most new work is SQL and data. |
| D-2 | `/features` limits (bbox cap, order, rounding) | T-20 → T-21 → T-22, T-23 |
| D-3 | Asset inspector data shape | T-20, T-23 |
| D-4 | Loader policy (null geometry, DDL) | T-55, and the DDL item deferred from T-51 |
| D-5 | What `/` shows | T-43 |
| D-6 | ArcGIS metadata GET | T-54 |
| D-7 | Where `DATABASE_URL` lives | T-58 |
| D-8 | Path of the DDL file | T-53 |
| D-9 | Whether to do schema migrations | T-56 |
| D-10 | Test runner | T-70 |

Other prerequisites that are not decisions:

| Prerequisite | What depends on it |
|---|---|
| User approval for one live read-only Neon run of `database/test_connection.py` | The last T-50 acceptance check |
| A running dev server for T-01 (the user may need to start it) | T-01, and through it T-10, T-11, T-40, T-41, T-70 |

Verification results are in the task board's
[Evidence log](task-board.md#evidence-log).

## 4. How work flows through the team

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
  MC -->|"1. records evidence"| BOARD[("task-board.md<br/>scope + Evidence log")]
  MC -->|"2. then sets status"| PROJ[("GitHub Project #1<br/>live status")]
  U -.->|"may move cards<br/>(authoritative)"| PROJ
  BOARD -->|"review"| TL
  QA -->|"fails"| OW
```

- Only the owner of a file edits it, and only one task edits a file at a time
  (CLAUDE.md, *Agents and file ownership*).
- A card moves to Done in Project #1 only after its verification results are
  recorded on the task board (CLAUDE.md, rule 10). Only the main conversation
  changes the Project; the user may also move cards directly.
