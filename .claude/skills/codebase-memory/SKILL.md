---
name: codebase-memory
description: Query the ORIGIN codebase's structural graph instead of sweeping files with Grep/Glob/Read. Use whenever the question is about structure rather than a specific known line - "where is X defined", "what calls X", "what breaks if I change X", "how does A reach B", "what are the entry points", "give me an overview of module Y", or any search whose answer would otherwise require reading several files. Also use before broad refactors, to find dead code, and to check what a change touches. Do NOT use for reading a file you already know the path of, or for non-code files.
---

# Codebase memory — ask the graph, not the filesystem

The ORIGIN codebase is indexed into a structural graph: functions, classes,
call chains, imports, and their relationships. **337 nodes, 1,272 edges.**

The point is token cost. A structural question answered by grepping means
reading many files to find a handful of relevant lines. The same question
against the graph returns just the nodes, with file paths and line ranges. On
this project that is a small win; the gap widens sharply as the codebase grows
and across context resets, where the graph remembers and the session does not.

## Project identifier

Every call needs this, verbatim:

```
C-DeepakJadhav-Personal-CockroachDB_AWS-Hackathon-origin
```

Root: `C:\DeepakJadhav\Personal\CockroachDB_AWS Hackathon\origin`

## Which tool for which question

| The question | Tool |
|---|---|
| "Where is X?" / "What handles Y?" | `search_graph` with `query` |
| "What calls X?" / "What does X depend on?" | `search_graph` with `relationship` + `include_connected` |
| "How does A reach B?" | `trace_path` |
| "Give me the shape of this codebase" | `get_architecture` |
| "Show me the actual code for this node" | `get_code_snippet` |
| "Find by name/file pattern, not meaning" | `search_graph` with `name_pattern` / `file_pattern` |
| "Full-text through source, not structure" | `search_code` |
| "What changed since the index?" | `detect_changes` |
| "What node types and relationships exist?" | `get_graph_schema` |

`search_graph --query` uses BM25 with structural boosting (functions +10,
routes +8, classes +5) and splits camelCase into words. `--semantic-query`
takes an **array** of keywords, not a string, and its hits come back in a
separate `semantic_results` field.

## Two ways to call it

**Preferred — MCP tools.** After a Claude Code restart the `codebase-memory`
server from `.mcp.json` exposes these directly. Use them.

**Fallback — CLI.** Works right now, no restart needed:

```bash
codebase-memory-mcp cli search_graph --project <project> --query "licence determination" --limit 5
```

Binary (not on PATH in every shell — use the full path if `codebase-memory-mcp`
is not found):

```
C:\Users\djadhav\AppData\Roaming\npm\node_modules\codebase-memory-mcp\bin\codebase-memory-mcp.exe
```

### Three PowerShell gotchas that will waste your time

1. **The tool logs to stderr on every run** (`level=info msg=mem.init ...`).
   PowerShell wraps that in an ErrorRecord and reports exit 1 even on success.
   It is not a failure. Redirect the streams to files and read stdout:

   ```powershell
   $out = "$env:TEMP\cmm.txt"; $err = "$env:TEMP\cmm_err.txt"
   Start-Process -FilePath $exe -ArgumentList $argstr -NoNewWindow -Wait `
     -RedirectStandardOutput $out -RedirectStandardError $err
   Get-Content $out -Raw
   ```

2. **Pass `-ArgumentList` as one quoted string, not an array.** An array splits
   multi-word values and you get `error: unexpected argument 'licence'`.

   ```powershell
   $argstr = 'cli search_graph --project ' + $proj + ' --query "licence determination" --limit 5'
   ```

3. **Use flags, not raw JSON.** Raw JSON is deprecated and its `project`
   argument is not read reliably — it fails with
   `missing required argument: project` even when present.

## Keeping the index honest

The index is a snapshot at commit `0d4abc3`. It does not update itself
(`auto_index = false`).

- After adding or restructuring modules, **re-index**:
  ```bash
  codebase-memory-mcp cli index_repository --repo-path "C:\DeepakJadhav\Personal\CockroachDB_AWS Hackathon\origin"
  ```
- Unsure whether it is stale? `detect_changes` before trusting a result.
- A stale graph is worse than no graph, because it answers confidently. If a
  result contradicts what you can see in a file, **the file wins** — then
  re-index.

## When not to use this

- Reading a file whose path you already know → use `Read`.
- Editing → use `Read` then `Edit`. The graph locates code; it does not replace
  reading the code you are about to change.
- SQL migrations, markdown, `.env`, config → not meaningfully in the graph.
- Anything under `.venv`, `.git`, `__pycache__` → deliberately excluded.
- A question about *runtime* behaviour. The graph is static structure; it will
  not tell you what actually executed.
