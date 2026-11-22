---
diagram_id: ""          # assigned by `python -m tools.design new diagram`: the owner's ID plus -D and a number (FD-0001-D1); never reused
title: ""               # required: the diagram's readable name
feature_id: ""          # required: the ID of the feature that owns this diagram
status: PROPOSED
source_diagram: ""      # when copied: its ID in designs/index/architecture-index.md, e.g. system-architecture/1-current-state-the-big-picture
source_document: ""     # when copied from an existing diagram, e.g. docs/architecture/system-architecture.md
source_heading: ""      # the heading anchor of that diagram, e.g. 1-current-state-the-big-picture
base_commit: ""         # the commit the copy was taken from: git rev-parse --short HEAD
---

# Proposed Diagram — [Diagram title]

| Field | Value |
|---|---|
| **Diagram ID** | [feature ID plus a number, e.g. FD-0001-D1] |
| **Feature** | [feature ID, with a relative link to its specification] |
| **Status** | <kbd>PROPOSED</kbd> |
| **Copied from** | [source diagram ID, with a link to its document and heading, or "new diagram"] |
| **Base commit** | [the commit the copy was taken from, or "n/a"] |

> **Evidence status legend:** ✅ **VERIFIED** = confirmed in the current repository (cite the source) · 🔷 **PROPOSED** = design or planned change · ❔ **UNKNOWN** = not yet determined
>
> **PROPOSED diagram**, not the implemented system. Copy this file into a `diagrams/` folder next to the feature and link it from the feature's "Proposed diagrams" section. Keep the metadata at the top and this table in step.

## Question this diagram answers

[One sentence: what the reader should understand from this diagram]

## Diagram

```mermaid
flowchart LR
  %% diagram-type: process
  A["Existing step"] --> B["New step (planned)"]
```

## What this diagram does not show

- [For example: exact parameters, performance, error handling]
