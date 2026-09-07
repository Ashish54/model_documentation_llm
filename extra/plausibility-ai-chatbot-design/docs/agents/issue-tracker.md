# Issue tracker

Issues are tracked as **local markdown files** in this repo, under `.scratch/<feature>/`.

Each feature or work item gets its own subdirectory under `.scratch/`. The exact file layout inside that subdirectory is flexible, but the convention is:

- `.scratch/<feature>/spec.md` — the specification for the work
- `.scratch/<feature>/ticket-*.md` — individual tickets derived from the spec (one file per ticket)

There is no remote issue tracker (no GitHub/GitLab remote is configured for this repo). Skills that read from or write to the issue tracker should create or update files under `.scratch/` rather than calling an external CLI.

**PRs as a request surface**: off (no remote repository configured).
