# Shared identity 0.1.0

Framework-independent tokens and the project catalog. `python3 pipeline/sync_shared.py` validates the catalog and generates `site/eding-shared.css` and `hub/`. The hub is a reviewable standalone proposal, not an automatic replacement for the existing apex site. The Scribe checkout carries a pinned copy; copy a new version deliberately and test both projects. Once the contract stabilizes, publish it as an independently versioned package.

Each application builds and deploys independently. ECERankings `npm run build` packages its existing validated dataset; it never refreshes OpenAlex. The public `version.json` identifies the build and hashes the data manifest. Dataset generation time is not a claim of complete coverage.
