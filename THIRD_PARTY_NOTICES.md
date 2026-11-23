# Third-party notices

Repocademy vendors these browser assets under `app/static/vendor/` so the UI works offline:

| Asset | Version | License |
|---|---|---|
| [D3](https://d3js.org) | 7.9.0 | ISC |
| [highlight.js](https://highlightjs.org) (core + python/typescript grammars) | 11.10.0 | BSD-3-Clause |
| [Inter](https://rsms.me/inter/) font | woff2 subset | SIL Open Font License 1.1 |
| [JetBrains Mono](https://www.jetbrains.com/lp/mono/) font | woff2 | SIL Open Font License 1.1 |

Loaded at runtime from the jsDelivr CDN only when a learner runs a Python exercise:
[Pyodide](https://pyodide.org) 0.26.4 (MPL-2.0).

Python dependencies (installed from PyPI, not vendored): FastAPI, Uvicorn, Pydantic, httpx,
py-tree-sitter, tree-sitter-javascript and tree-sitter-typescript (all MIT).

Courses in `showcase/` quote short excerpts of the open-source projects they teach:
psf/requests (Apache-2.0), pallets/flask (BSD-3-Clause) and expressjs/express (MIT).
Every excerpt links back to the exact commit it came from.
