# Vendored front-end libraries

Self-hosted (not loaded from a CDN) so they work under the app's existing
strict Content-Security-Policy (`script-src 'self'`) and don't add an
external runtime dependency.

| File                     | Library  | Version | License | Source                                    |
|---------------------------|----------|---------|---------|--------------------------------------------|
| `three.module.min.js`     | three.js | 0.160.0 | MIT     | https://www.npmjs.com/package/three        |
| `chart.umd.js`            | Chart.js | 4.4.4   | MIT     | https://www.npmjs.com/package/chart.js     |

Both ship their original license headers at the top of the file — do not
strip them. To upgrade, replace the file with a newer build of the same
package; no app code depends on internal library file structure beyond the
public API each exposes globally / via ES module import.
