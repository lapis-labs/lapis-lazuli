# How `lazuli setup` reads a model release manifest (v0)

Embedding models are an optional signal for lazuli's font judgements. `lazuli setup` installs one
only from a release manifest (`models/manifest.schema.yaml`) and only after every check below
passes. When any check fails it installs nothing, removes what it downloaded, and exits 1; every
other lazuli command keeps working without a model.

## Where the manifest comes from

- Default: the `manifest.json` asset of the newest release of `lapis-labs/lazuli-models`. The CLI
  holds that location as a constant; `--manifest PATH|URL` overrides it for tests and air-gapped
  installs, and `--from DIR` reads the files from a local folder instead of the network.
- Every request goes through `lazuli.catalog.net`, the only code that reaches a site. It gains a
  streaming download next to the catalog fetcher: HTTPS only, the lazuli User-Agent, no cookies or
  credentials, 401, 403, and 429 raised as Blocked, and redirects followed only to HTTPS hosts (a
  Hugging Face `resolve` URL redirects to its file CDN). Like every other request it reads
  robots.txt (Hugging Face allowed every path on 2026-09-27) and keeps the module's pacing between
  files. The SHA-256 in the manifest, not the host, is what setup trusts.

## Checks, in order

1. **Format.** The manifest validates against the schema. A `version` other than 0 is refused with
   the manifest version named.
2. **Consistency inside the manifest.** File paths are unique within a model. Each model has exactly
   one `weights` file. Every `license.file`, `license.notice`, `license.training_data`, and
   `gate.report` names a `files` path of the matching kind. A student's `teacher` names a teacher in
   the same manifest. `dims.prefixes` is descending and starts at `dims.full`, and every model has
   the same `dims`.
3. **Gate.** A model with `gate.beats_baseline: false` is listed but never recommended; it is
   installed only when the user names it with `--model`.
4. **Compatibility.** The installed lapis-design version is at least `specimen.min_cli` and the
   model's `requires.min_cli`, and the specimen generator's version constant
   (`lazuli.specimen.VERSION`, added with the generator) equals `specimen.version`. A model trained on
   other specimens would embed the user's fonts wrongly, so a mismatch is refused with the version to
   upgrade to. Until the generator exists, every manifest is refused at this step.
5. **Download.** Each file comes from
   `https://huggingface.co/<source.repo>/resolve/<source.revision>/<path>`, never a branch name, into a
   temporary folder in the user cache. Setup checks `bytes` while reading and `sha256` when done.
6. **Install.** Only when every file matches, the folder moves in one rename to
   `<user cache>/lazuli/models/<id>/<version>/`, with `installed.json` beside the files: model id and
   version, space id and version, specimen version, the chosen prefix length, the manifest's SHA-256
   and location, and the install time. Nothing else is written, and no license key or credential
   exists to store.

## After installing

- Setup prints the model's license id and the paths of its license and notice files, which stay
  beside the weights.
- Embeddings record the model, model version, specimen version, dimensions, and the space as
  `<space.id>@<space.version>` in `embedding.space_version`, so two spaces that share a version
  number never mix.
- Distances are computed only within one space. Embeddings from different models of that space may
  be compared, because the students are distilled into the teacher's space and each student's gate
  reports `cross_retrieval` against the teacher's index. When a manifest's `space.replaces` names a
  stored space version, those embeddings are marked stale and recomputed on the next scan that uses
  the model.
- `--dims N` chooses a trained prefix from `dims.prefixes`; any other length is refused.
- Without `--model`, setup suggests the first model whose `recommend` matches the device class and
  whose gate passed, and asks before downloading. `--yes` accepts the suggestion without asking.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | the chosen model is installed and verified, or was already installed with the same checksums |
| 1 | nothing was installed: no manifest, a failed check, or the user declined |
| 2 | usage error (unknown option or a missing value) |
