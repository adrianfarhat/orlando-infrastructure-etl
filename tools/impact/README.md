# Change-impact tool (`tools/impact`, T-83)

The tool answers three questions about this repository, using only Git and two
configuration files: [impact.yml](../../impact.yml) (purposes, ignores, interfaces, rules, reference scanning and
acknowledgement settings) and
[registry/components.yml](../../registry/components.yml) (components, their docs,
interfaces and dependencies).

| Command | Question | Inspects |
|---|---|---|
| `validate` | Are the configuration and registry sound? | The files in the working tree |
| `plan --paths …` | What would a change to these files involve? | Nothing changes; a prediction |
| `check [--base REF]` | What does this change affect, and what must be reviewed? | The actual changes |

Run every command from the repository root with the project virtual environment, for
example `.venv\Scripts\python -m tools.impact check --base main`.

The tool is read-only. It never modifies tracked files, runs no repository code, and
its only subprocess is `git`. The only files it writes are the reports requested with
`--out`.

## Typical workflow

1. **At task start:** `python -m tools.impact plan --paths <files you expect to change>`
   to see the components, docs, contracts, suggested tests (the test files of the same
   component) and dependents involved, and which
   `check` rules could apply.
2. **While working and before asking for review:** `python -m tools.impact check`
   (local changes against `HEAD`) or `python -m tools.impact check --base main` (the
   whole branch, committed and uncommitted).
3. **For the pull request:** `python -m tools.impact check --base main --format md`
   gives the "Documentation impact" section. Record review decisions about WARNINGs as
   acknowledgements (see below).
4. **After editing impact.yml or the registry:** `python -m tools.impact validate`.

## Commands

```
python -m tools.impact validate [--root DIR] [--format text|json] [--out [DIR]]
python -m tools.impact check    [--root DIR] [--base REF] [--ack-file FILE]
                                [--format text|json|md] [--out [DIR]]
python -m tools.impact plan     --paths PATH [PATH ...] [--root DIR]
                                [--format text|json|md] [--out [DIR]]
```

- `--root DIR`: the repository to analyse (default: the one containing the current folder).
- `--format`: what is printed to standard output (default `text`).
- `--out [DIR]`: also write every report of the command to `DIR`, a folder inside the
  repository (default `.local/impact/`, which Git ignores). `validate` writes
  `validate.txt` and `validate.json`; `check` writes `check.txt`, `check.json` and
  `check.md`; `plan` writes `plan.txt`, `plan.json` and `plan.md`. Each file is
  byte-identical to the corresponding standard output. The tool refuses a target outside
  the repository, the repository root, anything inside `.git`, and anything that would
  overwrite a tracked file or a folder. A failed write leaves either all old reports or
  all new ones, and removes folders it created. Use a Git-ignored folder: reports
  written elsewhere are new untracked files that the next `check` reports as changes.

### `validate`

Checks [impact.yml](../../impact.yml) and the registry against the working tree: schema,
listed docs, interfaces and contracts that do not exist (ERROR), patterns that match no
file and files matched equally well by several components (WARNING `registry-incomplete`;
checked for every file Git lists, tracked or untracked and not ignored by Git, that
impact.yml `ignore` does not exclude),
and file names the tool cannot analyse (WARNING `unsupported-path`).

### `check`

Compares the working tree with `HEAD` (origins `staged`, `unstaged`, `untracked`), or
with `--base REF` with the merge-base of `REF` and `HEAD` (adding `committed`). It
detects added, modified, deleted, renamed and copied files, reads their added and
removed lines, applies the rules below and the acknowledgements, and reports findings
plus an informational change-impact list. It refuses to run on an invalid configuration
or registry (exit code 2; run `validate`).

### `plan --paths`

Predicts, for existing or proposed files, what a change would involve. It inspects no
change: no diff and no changed lines. Paths are repository-relative. A backslash counts
as a folder separator and a leading `./` is dropped (write a name starting with `-` as
`./-name`). Absolute paths, `.` or `..` segments, empty paths, a trailing `/`, control
characters and folders are errors (exit code 2). A path Git does not list is a proposed
new file. A path ignored by Git (`.gitignore`, `.git/info/exclude` or the global
excludes file) is reported as ignored, because `check` never sees it. A tracked file is
never ignored by Git. A path in impact.yml `ignore` is reported as ignored too, but
`config-changed` is still predicted for it (shown in the JSON and Markdown reports; the
text report shows only that the path is ignored). Rules switched off in impact.yml are not
predicted.

## Findings and informational output

`check` produces two kinds of output:

- **Findings** are actionable. Each has a severity, a rule and a stable ID
  `<rule>:<10 hex characters>`. The ID is computed from the rule, the file, the location
  and the subject, never from line numbers or message text, so it survives unrelated edits.
- **The change-impact list** is informational: for each changed file, its components,
  purpose, every potentially affected doc with a "changed in this change set" flag,
  contracts, test files, one-hop dependents and content triggers. It has no IDs, needs no
  acknowledgement and never affects the exit code. A doc marked "changed" was changed in
  the change set; that is not a record that it was reviewed.

`plan` produces only predictions: no findings, no IDs, no acknowledgements.

### Rules

| Rule | Severity | Configurable | When |
|---|---|---|---|
| `new-interface-without-contract` | ERROR | No | A new file (added, renamed or copied to the path) matches an impact.yml `interfaces` pattern but is not listed in a component's `interfaces` with its contract. |
| `stale-reference` | ERROR | No | A file selected by impact.yml `reference_scan` still contains the exact repository path of a deleted file, or of the old path of a renamed file. |
| `unregistered-path` | WARNING | Yes | A changed file is in no component; the message suggests a component. A deleted file is not reported (nothing is left to register). |
| `docs-not-updated` | WARNING | Yes | Reported as "Documentation review required". A component with mapped docs changed, but none of its docs changed in the same change set. Files whose purpose is test, generated or experimental, and components with `docs: []`, create no obligation. |
| `content-trigger` | WARNING | Yes | A content trigger's `match` appears in the added or removed lines of a matching file (never the whole file). Changed lines that could not be scanned give a "not scanned" WARNING, never "no match". Not applied to test, generated or experimental files. |
| `config-changed` | WARNING | No | impact.yml, the registry, or one of the tool's own top-level Python modules changed. The tool finds its own folder at run time, relative to the repository root, so this works wherever the tool is placed in the repository. When the tool runs from outside the analysed repository (`--root` pointing elsewhere, or an installed copy), only impact.yml and the registry count. impact.yml `ignore` cannot hide these changes. |
| `ack-problem` | WARNING | Yes | An acknowledgement is malformed, unknown or stale, names an ERROR, has a bad reason, or is a duplicate. |
| `unsupported-path` | WARNING | No | Git reported a file name the tool cannot analyse. |

A configurable rule is set to `WARNING` or `off` in the `rules:` section of impact.yml.
ERROR rules and `config-changed` are fixed by the engine and cannot be lowered or
switched off. A "modified" file whose changed lines are empty (see the limitations)
creates no finding.

## Acknowledgements

An acknowledgement records a decision about a WARNING, for example that a mapped doc was
reviewed and needs no change. Put one per line in a file and pass it with
`--ack-file FILE`. Other lines are ignored, so a pull-request description can be used
as it is.

```
- ack docs-not-updated:81133de133: reviewed conventions.md section 5; no change needed because the workflow is unchanged
```

- **WARNINGs only.** An acknowledgement never removes a finding or changes its
  severity. The finding is reported as acknowledged, with the reason. An
  acknowledgement naming an ERROR is rejected, and the ERROR still counts.
- **Reasons are checked mechanically.** A reason must not be empty, must not be a
  placeholder from impact.yml `acks.placeholders` (for example "ok", "n/a", "no
  change"; compared without case and trailing `.` or `!`), and must be at least
  `acks.min_reason_length` characters (15). The tool cannot judge whether a reason is
  true.
- **Problems are reported as `ack-problem` WARNINGs**, and the acknowledgement is not
  applied: a malformed `- ack` line, an ID no current finding has (stale or mistyped),
  an ERROR, a bad reason, or a duplicate (the first valid one is used).
- **IDs are stable:** acknowledgements keep working when lines move. Acknowledgements
  have no owner or expiry field.

## Exit codes

| Code | `validate` | `check` | `plan` |
|---|---|---|---|
| 0 | No ERROR (WARNINGs allowed) | No ERROR; WARNINGs, acknowledged or not, never fail | The prediction was printed |
| 1 | At least one ERROR, including a missing or malformed impact.yml or registry | At least one ERROR (ERRORs cannot be acknowledged) | Never |
| 2 | Bad arguments, a Git failure, an unreadable file, an unusable `--out`, an internal error | As for validate, plus a bad `--base`, Git older than 2.44, an invalid or unloadable configuration, an unusable `--ack-file` | As for check: bad arguments or paths, configuration or Git failure, unusable `--out` |

An internal error always exits 2, never 1, so a bug cannot look like "ERROR found".

## Reports

- **Text** (default): one line per finding (severity, ID, file, location, message and,
  for `check` WARNINGs, `[acknowledged: reason]` or `[unacknowledged]`), then the
  informational list and a summary line.
- **JSON** (`--format json`): `schema_version` 1, with `summary`, `findings` (for `check`:
  `acknowledged` and `ack_reason`), `impact` or `predictions`, and exact values. Keys are
  sorted.
- **Markdown** (`--format md`, for `check` and `plan`): a "Documentation impact" table
  per component (docs, whether each changed, and the review or acknowledgement state),
  the findings table and the informational list, ready for a pull-request description.
  Names are escaped so they cannot form links, HTML or broken tables.

The same repository state and acknowledgements give byte-identical reports. Control and
format characters in names are escaped in text and Markdown.

## Safety

- Every Git call runs with `--no-optional-locks`, without fsmonitor, with Git hooks
  disabled (an empty hooks folder outside the repository), and with
  `GIT_NO_LAZY_FETCH=1`. In a partial clone, a missing object is never downloaded and
  the content is reported "not scanned". Change analysis needs Git 2.44 or later.
- `check` reads the index through a private copy outside the repository, so the
  repository's index and `index.lock` are never written.
- External diff programs and textconv converters are disabled.
- **Content filters (exception):** Git may run a content filter, such as Git LFS's
  `clean` filter, that `.gitattributes` selects and your Git configuration defines,
  when it compares a working-tree file. The tool does not run it directly and cannot
  safely prevent it without making those comparisons wrong.

## Known limitations

- **Phantom changes:** a staged edit later reverted on disk, a file deleted and
  recreated identically, or `git rm --cached` without an edit is listed as "modified"
  with no content change. Such entries create no finding.
- **Folders:** a file replaced by a folder of the same name is reported as "modified,
  not scanned".
- **Copies:** a copy of an unmodified file is classified as "added", not "copied"
  (Git's default copy detection); it is still fully scanned.
- **Not scanned:** binary files (including `.gitattributes` `binary` or `-diff`), files
  over 2,000,000 bytes, missing objects, submodules and nested repositories. These are
  shown as "not scanned", never as "no change".
- **Stale references:** only exact repository paths are matched. A root-level name such
  as `README.md` matches only when quoted or backticked. Links written relative to the
  document (for example `../../extractors/x.py`) are not checked; that is T-81, the link
  checker. URL-encoded paths, backslashes, different letter case and folder references
  are not matched. [docs/agents/task-board.md](../../docs/agents/task-board.md) is
  excluded as append-only history.
- **Tests** in the reports are the test files of the same component. That is a
  component-level suggestion, not a verified test mapping.
- **Speed:** reading changed lines takes about 37 ms per file. A pathological Markdown
  file with hundreds of thousands of matches can take minutes to scan for references.
- **Symbolic links** are read as their target path, as Git does; this was not verified
  on Windows.
- **Markdown:** GitHub turns bare `www.` and e-mail forms in names or reasons into links.
- **Acknowledgement lines:** near-miss lines (`- Ack`, `* ack`) are ignored without
  warning, and `- ack` lines inside code blocks count.
- **`plan`:** a path inside an untracked nested repository is predicted as an ordinary
  new file, although `check` does not analyse nested repositories.
