# Third-Party Notices

The companion extension is built against the following third-party libraries. They are fetched
from Maven Central by `fetch-deps.sh` and are **not** redistributed in this repository.

## Montoya API (`net.portswigger.burp.extensions:montoya-api`)

- Purpose: Burp extension API. **Compile-only** — provided by Burp at runtime and **not**
  bundled into `burp-autopilot-ext.jar`.
- License: MIT License. © PortSwigger Ltd.
- Source: https://github.com/PortSwigger/burp-extensions-montoya-api

## JSON in Java (`org.json:json`)

- Purpose: JSON parsing/serialization inside the extension. **Shaded** into
  `burp-autopilot-ext.jar` (classes under `org/json/`).
- License: Public Domain (the JSON License / "The Software shall be used for Good, not Evil").
- Source: https://github.com/stleary/JSON-java

Each library remains under its own license; see the respective projects for full terms.
