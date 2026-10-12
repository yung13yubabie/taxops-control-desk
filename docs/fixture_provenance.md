# Public fixture provenance

`tmp/BGMOPEN1.zip` is the existing government open tax-registration CSV fixture,
not an application database, customer export, or backup. It contains public
business registry fields such as business names, registration numbers, addresses,
capital, establishment dates, and industry codes. Its presence does not permit
publishing customer tax records or unrelated datasets.

- Official source: [Taiwan Ministry of Finance open data](https://eip.fia.gov.tw/data/BGMOPEN1.zip)
- SHA-256: `eea1c8be633f9ce13bb38096b96f547e02333da980f97fde9eac97012004cfa1`
- Scope: retained existing fixture for the complete registry import regression.
- Dataset: [財政部全國營業（稅籍）登記資料集](https://data.gov.tw/dataset/9400).
- Reuse terms: Government Data Open License, version 1.0 (see the dataset record).

Public business names and addresses may relate to natural persons; publicly
available does not mean free of personal-data considerations. Retention is limited
to the existing registry regression, not permission for unrelated redistribution.

The hygiene exception applies only to this exact path and hash. A replacement
requires checking its official provenance, applicable reuse terms, content, and
regression impact. Prefer small synthetic fixtures for new tests; do not bypass
review by exempting all ZIP, JSON, image, or test files.
