# Sugarscape baseline player

The bundled baseline reads `COWORLD_PLAYER_WS_URL`, selects a small readable
SugarLang ruleset from the observation's target ID and variable, submits it,
waits for a valid acknowledgement, and exits. It is intentionally simple and
intended as a qualification/certification baseline rather than a strong player.

For local development only, `--host`, `--port`, `--slot`, and `--token` can
construct the player WebSocket URL when `COWORLD_PLAYER_WS_URL` is absent.
