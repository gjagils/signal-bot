# /backlog-routine

Verwerk alle Linear issues in project **Signal-bot** met label `claude-ready` en status `Todo`.

## Stappen

1. **Log start** — noteer huidige datum/tijd (UTC).
2. **Haal issues op** via `mcp__Linear__list_issues`:
   - `project`: Signal-bot
   - `label`: claude-ready
   - `state`: Todo
3. **Per issue** (op prioriteit, hoogste eerst):
   a. Lees de volledige beschrijving via `mcp__Linear__get_issue`.
   b. Zet status op **In Progress** via `mcp__Linear__save_issue`.
   c. Maak een feature branch aan: `feat/GJA-<number>-<slug>`.
   d. Voer de implementatie uit.
   e. Commit & push naar de feature branch.
   f. Zet status op **Done** via `mcp__Linear__save_issue`.
4. **Branch cleanup** — na het laatste issue:
   - Identificeer alle remote branches zonder commits ahead van `main`.
   - Verwijder lege lokale branches (`git branch -d`).
   - Verwijder lege remote branches (`git push origin --delete`).
5. **Log einde** — noteer datum/tijd en bereken duur.
6. **Samenvatting** — rapporteer verwerkte issues, overgeslagen issues, en verwijderde branches.

## Wanneer geen issues gevonden

Rapporteer dit expliciet en ga direct naar stap 4 (branch cleanup).
