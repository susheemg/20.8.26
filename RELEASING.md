# Release process (no terminal needed beyond one script)

Every change ships as a **version**. The repo carries three markers that must agree:
`VERSION` (the number), `CHANGELOG.md` (what changed), and a git **tag** (`v4.1.0`).

## Cutting a release
1. Edit `VERSION` — bump per SemVer (breaking = major, feature = minor, fix = patch).
2. Add a section to `CHANGELOG.md` for that version (date + bullets).
3. Run `./release.sh` — it sanity-checks the app, verifies VERSION appears in the
   changelog, commits, tags `v<VERSION>`, and builds `Brata_TPRM_v<VERSION>.zip`.
4. Push to GitHub **with tags**: `git push && git push --tags`
   (GitHub Desktop: Repository → Push, with "include tags" enabled).
5. On GitHub: Releases → "Draft a new release" → choose the tag → paste the
   changelog section → attach the zip. Render auto-deploys from the push.

## Day-to-day commits
- Commit messages: `area: what changed` (e.g. `exit: Viny drafts respect alternatives`).
- Never commit secrets — keys live in Render env vars / `BRO_SECRET_KEY` encryption.
- `main` should always pass CI (it runs the full test suite on every push).

## Rolling back
Render → Deploys → "Rollback" to the previous deploy, or `git revert` the commit
and push. Tags make it unambiguous which code any deployment ran.
