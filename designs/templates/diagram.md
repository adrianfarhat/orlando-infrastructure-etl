---
diagram_id: ""          # the feature ID plus a number, for example FD-0001-D1
title: ""
feature_id: ""          # the feature this diagram belongs to
status: PROPOSED
source_document: ""     # when copied from an existing diagram, e.g. docs/architecture/system-architecture.md
source_heading: ""      # the heading anchor of that diagram, e.g. 1-current-state-the-big-picture
base_commit: ""         # the commit the copy was taken from: git rev-parse --short HEAD
---

# Diagram title

> **PROPOSED diagram**, not the implemented system. Copy this file into a `diagrams/`
> folder next to the feature and link it from the feature's "Proposed diagrams" section.

What question this diagram answers:

```mermaid
flowchart LR
  %% diagram-type: process
  A["Existing step"] --> B["New step (planned)"]
```

What this diagram does **not** show or prove:

- _for example: exact parameters, performance, error handling_
