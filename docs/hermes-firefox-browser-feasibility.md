# Historical Camofox migration plan for Hermes browser and secure-browser surfaces

This document is retained as historical investigation. It has been superseded by
Joy's current product split:

- `camofox.eyrie` is the ordinary Camofox/Camoufox REST browser API for standard
  Hermes browser tools.
- `browser.eyrie` is the persistent secure browser: a singleton Firefox/KasmVNC app
  using the Nest-owned `registry.gitlab.joyfullee.me/nest/tools/firefox:latest`
  image for the current cutover work.
- Current Firefox/Kasm implementation and bridge guidance lives in
  `docs/firefox-secure-browser-bridge.md`.
- Current Camofox surface guidance lives in `docs/camofox-browser-surfaces.md`.

The old recommendation to make the secure browser a Camofox/noVNC service is no
longer active guidance. Do not use this historical plan to add a Camofox REST API
at `browser.eyrie`, to expose raw CDP/WebDriver/VNC endpoints to models, or to
repoint final-purchase execution away from the reviewed Firefox secure-browser
bridge.
