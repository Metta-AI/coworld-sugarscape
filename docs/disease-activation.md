# Disease activation and image qualification

Disease penalties now apply once per active infection. Repeated disease ticks preserve the modifier; recovery removes it once.
Latent recovery does not subtract a penalty that never applied. ZombieVirus retains its incubation and upstream configuration.
The upstream submodule is unchanged. The wrapper and simulation integration live in `src/coworld/`.

## Measured result

This fixes an accounting invariant. It does not rescue the diagnosed policies.
Both original replay seeds scored zero before and after the fix.
Seed 114126312 became extinct at tick 97 instead of 109.
Seed 114126317 became extinct at tick 144 instead of 96.
Two independent fixed-source runs per seed produced identical complete replay bytes and canonical results.
The input manifest and 75 consumed files were independently checked against their Git pins.

The original attempt record contained copied, unused legacy source fields.
Those fields are retained as an error. The immutable input manifest establishes the actual consumed source.
See [the evidence receipt](disease-activation-evidence.json) for exact source, artifact and replay identities.

## Build and run

Initialize the pinned upstream code before building either image:

```sh
git submodule update --init
docker build --file Dockerfile --tag sugarscape-game:qualified .
docker build --file players/baseline/Dockerfile --tag sugarscape-baseline:qualified .
```

Both Dockerfiles pin Python 3.13.5 and websockets 17.0.1.
The game starts `python -m coworld.server`; the player starts `python -m players.baseline.player`.
No copied virtual environment or host Python source is required by either image.

For the regular local game, use `docker compose up --build`.
The Compose configuration supplies the game config, result/replay paths and baseline WebSocket URL.
`config.json` must contain one token and player name per seat.

For a bounded image acceptance check, create an owned output directory containing `config.json` and the bundled `players/` and `tools/` directories under `source/`.
Use a resolved one-seat config with a fixed seed and target, no `scenario_pool`, at most 1000 timesteps, and a connection timeout of at most 30 seconds.
The harness replaces the local token and player name. It does not use hosted credentials.

```sh
mkdir -p build/image-proof/source
cp -R players tools build/image-proof/source/
cp tests/fixtures/disease-image-config.json build/image-proof/config.json
python tools/qualify_game_image.py \
  --output "$(pwd)/build/image-proof" \
  --game-image sugarscape-game:qualified \
  --player-image sugarscape-baseline:qualified
```

The harness checks the default image commands and creates a unique Docker network and containers.
It rejects an invalid token before connecting the real bundled player.
After the complete episode, it decodes every saved frame and compares canonical results with the native oracle inside the same game image.
An invalid config must fail without publishing results.
Game and player CPU quotas total one CPU; the sequential oracle uses one CPU.
Logs, inspections, results and replay remain in the output directory.
Containers run as the owning UID and GID, so private replay files remain readable by their publisher.
Owned containers are stopped and joined before removal, including on failure or signal.
Other containers, images and networks are untouched.

## Limits

The observed game-image episode also scores zero. Passing runtime fidelity does not establish policy improvement.
The supporting engine correction does not authorize uploading a new hosted game version or reinterpreting historical league results.
Per-league candidate comparison and scoped promotion remain separate gates.

## Published image receipt

The complete CPU qualification passed in 106.51 seconds on Titan, with no GPU or paid allocation.
The source was `dc9ea5da3ddb941172215ac267f03b6972f834c3`; runtime/image files are unchanged from `7d751b155d1b63f327b386917d8383710e289dc9`.
The game image is `sha256:3fad950570e5ee7ad9fb654db500d1e8fbb81446aad47037a32a4d6e95e47c6f`.
The baseline image is `sha256:262f26b06d8c4b421932960ea3dd830686c686b3badc4b327200dd4d78121bae`.

Authorized sandbox readers can retrieve both images together:

```sh
aws --profile sandbox s3 cp \
  s3://softmax-slurm-artifacts/relh/october-20261002-engines-policy-cleanup-17/current-game-images/102c78152b69481fb8686eaa4f553598/images.tar \
  disease-images.tar
echo "fd364b53ebe21b720132d835eabdb4bbae3a8691c8e20902745dbf702d2053c4  disease-images.tar" | sha256sum --check
docker load --input disease-images.tar
```

The 48,380,416-byte archive was uploaded, read back completely, hash-checked and reloaded.
Both reloaded image identities and the native replay oracle matched.
Use `relh-53-disease-game:102c78152b69481fb8686eaa4f553598` and `relh-53-disease-player:102c78152b69481fb8686eaa4f553598` as the harness image arguments.
Saved results and every gameplay frame matched the oracle; the baseline received a valid action acknowledgement.
The invalid-token probe returned 403, and invalid configuration exited 1 without results.

The first attempt passed game and image checks but failed final packaging because root-owned replay files were mode 0600.
Its original failure and recovered artifacts remain separate.
The corrected owning-user attempt completed publication without that failure.
The fixture and workflow now exercise the ordinary path instead of treating an engine import as complete image acceptance.
