# Pinned research sources

These are pinned research inputs from reviewed studies in Metta-AI/sugarscape.
Run `python tools/fetch_research_sources.py` before native setup or local episodes.
Setup and Docker builds download selected files from immutable public Git commits or the hash-pinned author release.
Downloads are verified before writing, ignored by Git, and included in the image for offline episodes.
Existing downloaded files must match their pins; setup fails rather than replacing local edits.
`manifest.json` pins each commit and every file hash. Runtime verifies those hashes before importing a model.
Update snapshots from an explicitly reviewed commit, preserving their corresponding notices and validation evidence.

McCulloch's study model preserves the MIT-licensed released implementation's behavior, including initialization collisions.
Its author notice is retained beside the map. The independent study implementation comes from the Unlicense research fork.
Carrella's reconstruction follows a CC BY-NC-SA 3.0 author model; see its retained source header and the linked study's license discussion.
Izquierdo's implementation and figure-derived map support controlled constructive paths; they are not an unbiased sampler of stationary dynamics.
Original research evidence and full provenance remain in the pinned source commits. These snapshots add no historical-equivalence claims.

Dogan's original `sugarscape_ai_tax` package retains its MIT license, Apache dependency license and NOTICE.
The source pin is the reviewed study branch, with unchanged model files; tax calibration is performed before the episode.
Brearcliffe's model and license come from the author's released archive retained by the study.
The model, license and symmetric map are restored from the unchanged, hash-pinned author release.
`Replay.java` is the study recorder, preserving `with-local-randomness` around observations.
Oremland's model is the explicitly documented study reconstruction, not recovered author source.
Its unchanged `RunPolicyBatch.java` exports the original evaluator endpoint and survivor-state hash.

The NetLogo runtime archives are official distributions pinned by `netlogo-runtimes.json`.
Build-time setup verifies complete archive hashes before extraction and retains distribution notices under `app/`.
Per-episode checks verify every runtime jar and compiled recorder/extension file against the build qualification.
These third-party notices and terms are not replaced by the research fork's root license.

Quera retains the author's MIT-licensed DiffABM.jl source at commit `9178eccd56dd352e3515e276239654239f8d3b41`.
`Manifest.toml` is the qualified study's forward dependency lock, not an author-supplied historical lockfile.
The adapter executes only forward dynamics; BlackBIRDS, flow fitting and the 5,000-epoch campaign remain external research.
