# South Florida Default Study Area

## Current default

- study area name: `south_florida_florida_straits`
- start date: `2023-01-01`
- end date: `2023-06-30`
- bbox: `[-82.0, 24.2, -79.4, 27.2]`

## Why this was chosen

- likely to include a better mix of `Cargo`, `Tanker`, `Passenger`, `Fishing`, and leisure-related traffic than the Gulf sample we already inspected
- NOAA coastal AIS receiver coverage should be stronger here than in farther offshore test areas
- Sentinel-2 revisit timing is favorable for repeated opportunities across a dense maritime corridor

## Why not reuse the current Gulf sample area

The local NOAA sample already inspected in this workspace is centered roughly around:

- latitude: `28.28` to `29.63`
- longitude: `-88.47` to `-86.78`

That sample appears useful for pipeline testing, but it looked weak for a six-class external evaluation because `Sailing` and `Pleasure` traffic were sparse in the mapped target classes.
