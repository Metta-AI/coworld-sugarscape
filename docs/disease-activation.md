# Disease activation and image qualification

Disease penalties apply once per active infection; recovery removes them once. Latent recovery removes no unapplied penalty.
Reinfection, shared infections and ZombieVirus incubation retain their behavior. The upstream submodule remains unchanged.
The image qualifier uses the production Python episode path, independently of PR #41's experimental Nim simulator.

## Preserved evidence

This fixes accounting, not policy performance. Both diagnostic seeds scored zero before and after the fix.
Seed 114126312 became extinct at tick 97 instead of 109; seed 114126317 at tick 144 instead of 96.
Two independent corrected runs per seed matched complete replay bytes and canonical results; 75 consumed files matched their pins.
The reference is `82cc74246c3f58628072f878cdc551d335aa0ae8`, correction `c90e717f67042daf276f60db4ebdafc6732dc4d1`, upstream `d0b0e95ef58f191e32d832a661831f4314df2d64`.
Copied, unused legacy fields in the original attempt were erroneous; its immutable input manifest establishes the consumed source.

The [full original receipt](https://github.com/Metta-AI/coworld-sugarscape/blob/883f2b8a28f9b38c7b7c96814470b2e378b2f92d/docs/disease-activation-evidence.json)
retains every source cohort, replay/artifact hash, failed attempt and recovery record.
Its SHA-256 is `265094195da747d5bbfd55734a32021bda23b8aae1103024483288fe8360956b`.
The original PR reported 44 CPU test passes; the same four-file scope currently collects and passes 22 tests. The historical count is not reproduced.
Image qualification took 106.51051509700483 seconds on Titan, one CPU and no GPU or paid allocation.
Source `dc9ea5da3ddb941172215ac267f03b6972f834c3` retained runtime/image bytes from `7d751b155d1b63f327b386917d8383710e289dc9`.
All 144 gameplay frames and canonical results matched the Python episode oracle; score remained zero.
The invalid-token probe returned 403; invalid configuration exited 1 without results.
The first attempt passed gameplay but failed packaging on root-owned mode-0600 replay files. Its failure and recovered artifacts remain separate.
The corrected attempt ran containers as the owning UID/GID and completed publication and full archive readback.

| Published artifact | Exact identity |
| --- | --- |
| Game image | `sha256:3fad950570e5ee7ad9fb654db500d1e8fbb81446aad47037a32a4d6e95e47c6f` |
| Baseline image | `sha256:262f26b06d8c4b421932960ea3dd830686c686b3badc4b327200dd4d78121bae` |
| Image archive (48,380,416 bytes) | `fd364b53ebe21b720132d835eabdb4bbae3a8691c8e20902745dbf702d2053c4` |
| Replay | `cd11dc86c1c8b55f21585f9e9c30a64fb5120480a1078969cc61c3d776e0c447` |

The receipt contains the sandbox S3 key, image tags, artifact identities and original source manifests.
These are historical measurements, not a qualification of later source or evidence of policy improvement.
Hosted upload, per-league comparison and promotion remain separate gates.

## Maintained controls and local qualification

`tests/test_disease.py` covers activation, latent recovery, reinfection, shared state, ZombieVirus and factory restoration.
`tests/test_game_image.py` exercises full replay parity and corrupted-result rejection with the existing tiny episode fixture.
`tools/qualify_game_image.py` retains Docker default-command checks, invalid-token/config probes, resource limits and owned-container cleanup.
For an independently authorized image qualification, initialize the pinned submodule and build both Dockerfiles.
Both pin Python 3.13.5 and websockets 17.0.1; ordinary local play uses `docker compose up --build`.
Recover the exact historical one-seat configuration instead of maintaining a generated copy:

```sh
mkdir -p build/image-proof/source
cp -R players tools build/image-proof/source/
git show 883f2b8a28f9b38c7b7c96814470b2e378b2f92d:tests/fixtures/disease-image-config.json > build/image-proof/config.json
echo '72ac612bab1b60ffc0aaaea853add709b2068886da0e153733919bea0c03cc5a  build/image-proof/config.json' | sha256sum --check
python tools/qualify_game_image.py \
  --output "$(pwd)/build/image-proof" \
  --game-image sugarscape-game:qualified \
  --player-image sugarscape-baseline:qualified
```

Build the game with `docker build -f Dockerfile -t sugarscape-game:qualified .` and the player with
`docker build -f players/baseline/Dockerfile -t sugarscape-baseline:qualified .` after `git submodule update --init`.
The harness replaces local credentials, uses one CPU in total, and preserves logs, results and replay in the owned output directory.
