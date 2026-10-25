# Stable LibreOffice validation environment

This environment retains the existing Python application and verifies Writer, Calc and Impress with fictional data. It is a development/CI tool, not an institutional deployment or approval.

## Version policy

`Dockerfile.libreoffice` uses Python 3.12 on Debian 13 (trixie), with the base image pinned to the registry-resolved digest in its FROM line. Calc, Writer and Impress are pinned to Debian's security-maintained package `4:25.2.3-2+deb13u8` (LibreOffice reports `25.2.3.2`). This is the Debian-maintained distribution build, not a claim to the newest upstream LibreOffice release. Prerelease/development version strings are rejected at build and smoke time.

The image records its base reference, all installed Debian packages, LibreOffice version and `pip freeze` under `/opt/cdf-runtime/`. Core Python requirements retain the existing lock. Optional API requirements and transitive OS/Python dependencies can change as repositories evolve. The recipe is version-traceable but not a bit-for-bit immutable artifact. For immutable reuse, retain the successfully tested image by digest in an authorized registry or save it as an artifact; this task does not authorize registry publication.

## Build locally

Docker with a running daemon is required. From the repository root:

```sh
docker build --progress=plain -f Dockerfile.libreoffice -t cdf-lo-stable .
docker image inspect cdf-lo-stable --format '{{.Id}}'
docker run --rm --init --network none cdf-lo-stable sh -c \
  'cat /opt/cdf-runtime/base-image.txt /opt/cdf-runtime/libreoffice.txt; cat /opt/cdf-runtime/packages.tsv'
```

The `.dockerignore` is an allowlist: only the Dockerfile and two dependency manifests enter the build context. Source, Git history, private data, keys and databases are excluded. The application source is supplied at runtime, not baked into the image. Other Dockerfiles will need an explicitly reviewed context policy if introduced later.

Prepare **committed tracked public source** in an isolated directory so local private or ignored files are not mounted:

```sh
validation_source=$(mktemp -d)
validation_evidence=$(mktemp -d)
git archive HEAD | tar -x -C "$validation_source"
docker run --rm --init --user "$(id -u):$(id -g)" --network none --cap-drop ALL --security-opt no-new-privileges \
  --mount "type=bind,src=$validation_source,dst=/repo" \
  --mount "type=bind,src=$validation_evidence,dst=/evidence" \
  cdf-lo-stable python tools/libreoffice_validate.py --evidence /evidence
```

Keep `validation_evidence` for review; remove the temporary source afterwards. Do not mount credentials, host runtime binaries, private documents or signing material. No host `soffice` or Python wrapper is used by the container.

Run only the smoke checks if diagnosing startup:

```sh
docker run --rm --init --user "$(id -u):$(id -g)" --network none \
  --mount "type=bind,src=$validation_source,dst=/repo" \
  --mount "type=bind,src=$validation_evidence,dst=/evidence" \
  cdf-lo-stable python tools/libreoffice_smoke.py --report /evidence/smoke.json
```

## Acceptance and evidence

The smoke tool creates temporary XLSX, Arabic DOCX and ODP fixtures using existing dependencies and stdlib. It uses fresh profiles and separate outputs, hashes original inputs, confirms an uncached SUM computes to 5 while preserving the formula, and parses PDF pages/readable markers. Writer also requires readable Arabic characters. It refuses a missing or prerelease runtime. Every launched process has a timeout; its isolated process group is terminated on timeout, without killing unrelated LibreOffice sessions.

`tools/libreoffice_validate.py` runs smoke first, the six required LibreOffice-dependent tests (including their full e2e module prerequisites) second, then `tests qa_public`. It checks JUnit identity and outcomes so required engine tests cannot silently disappear, skip, error or fail. The full suite may still skip missing institutional fixtures and unconfigured real-provider tests, with reasons reported separately. No unavailable-engine override is used.

Evidence includes smoke JSON with package provenance, per-stage logs, and engine/full-suite JUnit. Valid source exports and formula comparisons are required; process exit status or output existence alone is not sufficient. Artifacts are synthetic, not evidence of real provider execution or institutional acceptance.

## GitHub Actions

`.github/workflows/libreoffice-stable.yml` builds locally on an Ubuntu 24.04 runner, records image/package identities, exports tracked source, runs the validation without network access and uploads diagnostics even on failure. It does not push an image. The existing Python, web-build and browser workflows remain intact. The new workflow covers the project's stacked PR bases, including the takeover branch.

Check the workflow on the exact PR head before accepting a change; previous-head success is historical evidence only. The job-level 45-minute bound and per-stage bounds prevent unbounded runs; cleanup targets only this job's named container.

## Codex cloud and proxy handling

Committing this Dockerfile does **not** install LibreOffice in an existing Codex host or configure its reusable environment. In a compatible managed cloud environment with Docker enabled, run the same image and tests through the managed daemon. If the platform requires an environment setup change, configure/test/publish that environment through its supported settings separately. Do not replace the host's managed runtime or claim that repository files changed it.

For managed HTTPS interception, preserve configured proxy routing and pass the combined CA bundle as a BuildKit secret:

```sh
docker build --secret id=proxy_ca,src=/etc/ssl/certs/ca-certificates.crt \
  -f Dockerfile.libreoffice -t cdf-lo-stable .
```

Use the platform-provided combined CA bundle path when different. The optional secret configures trust for apt/pip only during networked RUN steps; it is not copied into the image. Do not disable TLS checks, dump Docker credentials, bypass a blocked destination or use host networking to evade policy. Runtime validation requires no network/provider credentials.

## Updates and troubleshooting

- Update the base digest from an actual successful registry pull and resolve package candidates inside that base. Update the package pin deliberately, rebuild and rerun all acceptance checks. Never invent a digest or silently fall back if a pinned package disappears.
- Retain build logs, smoke provenance and the built image identity. A verified recipe with moving transitive dependencies is not an immutable image; use a preserved tested image digest when exact reproduction is required.
- Socket denial: confirm the selected Docker daemon is available through the supported environment; LibreOffice needs local sockets inside the container. Do not treat an installed binary as proof it can execute.
- Profile lock/timeouts: use unique temporary profiles and keep inputs/output directories separate. The original host alpha runtime failed tiny Calc probes; see LIBREOFFICE_DIAGNOSTIC.md. Validate this stable container before diagnosing workbook-specific problems.
- Fonts: the container includes Noto Arabic fonts and Carlito (Calibri-compatible). Text checks do not certify pixel-perfect Arabic typography or identical pagination across platforms.
- Formula differences: Calc is an independent spreadsheet engine; reconciliation does not prove Microsoft Excel equivalence. Preserve formula assertions and independently test Excel if it is the production consumer.
- Failure: inspect smoke.json and JUnit/log artifacts. Do not disable LibreOffice, inject Python caches or weaken comparisons to make the job green. ENV-01 is resolved for the verified stable container: smoke and actual project engine checks pass. The historical host alpha failure remains an environment limitation.

## Local verified result
Local image ID: sha256:701893538967e5ac5e559d8623c17d228fbcebbaafc38b49bf2aed5a1c2eabbc. Smoke: 3/3 passed. Engine/prerequisite run: 13 passed, no skips. Full suite: 243 passed, 11 skipped, 10 subtests passed in 95.77s. See TEST_EVIDENCE_REGISTER.md for limits; these are local results, not a substitute for exact-head CI.
