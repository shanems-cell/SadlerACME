# Bundled upstream components

SadlerACME: **Original project by Shane Sadler**. Its original files are licensed under GNU GPL version 3 only (`GPL-3.0-only`), selected by the project owner on 26 September 2026; see the project [LICENSE](../LICENSE) and [NOTICE.txt](../NOTICE.txt).

The `acme.sh-3.1.5` directory contains unmodified `acme.sh`, `dnsapi/dns_cf.sh`, and `LICENSE.md` from the acmesh-official/acme.sh 3.1.5 tag. The upstream licence is included in that directory. The application runs this bundled local copy and checks fixed SHA-256 digests before executing it; it does not download or automatically upgrade executable code at runtime. ACME issuance and Cloudflare DNS operations still require network access. Offline regression tests use fixtures instead of those live services.

Those bundled components retain their upstream authorship, licence and notices. The SadlerACME project credit does not replace upstream attribution.

Source: https://github.com/acmesh-official/acme.sh/tree/3.1.5

acme.sh SHA-256: `812c228e9c6374b99c8bd615ca8172b6dd483bd93a5ce862f58531e461d04be8`

dns_cf.sh SHA-256: `9628ee8238cb3f9cfa1b1a985c0e9593436a3e4f8a9d65a6f775b981be9e76c8`
