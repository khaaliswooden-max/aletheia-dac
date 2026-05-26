# Contributing to Aletheia

Thanks for contributing. This project is a *safety substrate*, so contributions
are held to a slightly higher bar than typical: a change that weakens a
guarantee is a regression even if every test passes.

## Before you start
Read `CLAUDE.md`. It is the canonical design contract and applies to human and
agent contributors alike. The single non-negotiable invariant is **monotone
propagation** (see `CLAUDE.md` and the IEEE paper, `paper/aletheia.tex` §IV).

## Development setup
```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q            # expect: 7 passed
```

## Definition of done (every PR)
1. `pytest -q` passes 7/7 **without weakening the T3/T4/T6 assertions**.
2. New behavior is covered by a *falsifiable* test (state the property it
   would violate if broken).
3. The monotone-propagation invariant is preserved:
   confidence `min`, classification `max`, validity intersection, HITL `or`,
   stale-is-absorbing.
4. The audit chain is never broken by mutating a stored claim's signed `json`
   in place — legitimate state changes live in the `status` column only.
5. Epistemic markers (VERIFIED / PLAUSIBLE / SPECULATIVE) used in docs and
   non-obvious comments.
6. If the change narrows or widens one of the six known open gaps
   (see `docs/Specification.md` §6 and the paper §Limitations), say so
   explicitly in the PR description and update that list.

## Things we will not merge
- A "fix" to a known gap that is actually a silent assumption (e.g. treating
  `min`-combination as solved by switching to `mean` without a calibrated
  justification). Treat gaps as research: propose a design, add a failing test
  encoding the target property, then implement.
- Edits to acceptance tests that accommodate a weaker guarantee.
- New required dependencies in `cli.py` — it must stay stdlib-only so it runs
  anywhere on the zero-budget stack.

## Commit conventions
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`).
- Sign off each commit (`git commit -s`) to certify the
  [Developer Certificate of Origin](https://developercertificate.org/).

## Reporting issues
Use the issue tracker for bugs and design questions. For anything with security
or integrity implications, follow `SECURITY.md` instead.
