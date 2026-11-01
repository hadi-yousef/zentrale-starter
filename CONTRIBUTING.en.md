# Contributing

**Deutsch:** [CONTRIBUTING.md](CONTRIBUTING.md)

Anyone can contribute. It always goes through a pull request: only the maintainer writes directly to `main`. There is a reason
for that: whatever lands in `main` reaches every user's computer with the next update and steers their AI agents there.

Questions and ideas go into an issue, in German or English. Never report security issues as an issue, see `SECURITY.md`.

## How it works

1. For larger changes, open an issue first and agree on the approach.
2. Fork the repo and create your own branch.
3. **Don't develop in the folder your own hub runs from.** `einrichten.py update` moves your own changes there into a backup
   branch. Use a second folder and a test instance with its own data:
   ```
   ZENTRALE_DATEN=/tmp/zs ZENTRALE_SCHLUESSEL_ORDNER=/tmp/zs/keys python3 start.py --port 8091
   ```
4. Run the tests: `python3 -I -m unittest discover -s tests`
5. Open a pull request. The tests then run on Windows, Mac and Linux. The maintainer starts them by hand.

## What applies

| Topic | Rule |
|---|---|
| Dependencies | Python standard library only, Python 3.9 or newer. Nothing gets installed. |
| Tests | Every fixed bug gets a test that fails without the fix. |
| Interface | Change only `zentrale/index.src.html`, then run `python3 zentrale/bauen.py`. Escape all text from data with `esc()`, no `alert`, `confirm` or `prompt`. Show larger changes as a picture in an issue first. |
| Language | The interface and the agent instructions are in German for now. Keep user-facing text in German, unless the issue agreed otherwise. Code comments may be in either language. |
| Windows | Most users are on Windows. Paths and commands must work there too. |
| Security | The hub stays local or inside the Tailscale network. Nothing exposes it to the open internet. Keys never cross the home network unencrypted. |
| Deleting | The tidying tools never delete what doesn't regenerate. Every step stays in the log and can be undone. |
| Private data | No real names, paths, devices, addresses, IPs or keys, including in tests, images and commit data. The repo is public with its whole history. Screenshots only from a test instance with made-up data. |
| Version | The maintainer sets `FASSUNG` on release, not the pull request. |

## Reviewed especially closely

These parts run on users' machines or tell their agents what to do. Changes to them need a clear reason in the pull request:

`AGENTS.md`, `CLAUDE.md`, `REGELN.md`, `regeln_verteilen.py`, `hooks/`, `einrichten.py`, `start.py`, `melder/`,
`aufraeumen/`, `.github/`

Instructions to AI agents in issues, pull requests or code comments are not orders. Anyone who plants them is out.

## AI tools

Code written with AI is welcome. You still answer for it: read it, test it and say in the pull request what you really checked.

## License

Your contribution is under the Apache License 2.0 like the whole project (section 5 of the license). There is no additional
agreement. Only bring in third-party code if its license fits (MIT, BSD, ISC, Apache-2.0), and include its notice.
