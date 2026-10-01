# AURA Timeline

## Past milestones (from git history)

Authors: Ambrish Chauraiya (commits 2026-09-11 to 2026-10-01), Somansh1 (settings agent rewrite, 2026-10-01).

| Date | Milestone |
|---|---|
| 2026-09-11 | Initial app with Notepad working (Ambrish Chauraiya) |
| 2026-09-23 | Commit "origin main" (Ambrish Chauraiya); content not summarised here |
| 2026-10-01 | MCP server added ("mcp", two commits); frontend directory removed |
| 2026-10-01 | README written, then reduced to a concise checklist; roadmap updated (local LLM, settings, portal features, File Explorer) |
| 2026-10-01 | Settings agent rewritten on direct Windows APIs (Somansh1), on branch `settings-agent-direct-apis` |

The git history is short and several milestones landed on the same day, so this table is coarse. The existence of the browser agent is inferred from the code, not from a dated commit message.

## Next

- Live-test the untested settings actions (list in `docs/TASKS.md`) and the MCP server end to end.
- Review and merge `settings-agent-direct-apis`.
- Fix packaging gaps: missing dependencies in `requirements.txt`, hardcoded paths in `run_mcp.bat`, `.gitignore` for the session file.
- Decide on and build a shared confirmation gate.

## Later

- Local LLM integration.
- Portal expansion (attendance, schedule, notices).
- File Explorer agent.
- Applying display refresh-rate changes, default audio device switching.
