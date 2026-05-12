# Rough System Requirements for ~5,500 Patches

These estimates are intended for local planning, not as strict minimums.

## Practical recommendation

- CPU: `6-8` cores
- RAM: `32 GB`
- Free disk: `250-500 GB`
- GPU: optional for patch generation, useful for retraining or faster inference

## Why the disk estimate is larger than the final patch size

The final patch set itself is not large.

From the current workspace dataset:

- average patch file size is about `68 KB`
- `5,500` patches correspond to about `376 MB`

However, local disk usage also needs to cover:

- raw NOAA CSV files
- normalized intermediate tables
- Postgres/PostGIS data files
- Sentinel-2 SAFE ZIP archives
- temporary extracted `JP2` band files
- optional `TCI` outputs and analysis figures

## Safe planning tiers

### Small pilot

- target: `500-1,000` final patches
- RAM: `16 GB`
- free disk: `100-150 GB`

### Full target

- target: about `5,500` final patches
- RAM: `32 GB`
- free disk: `250-500 GB`

### If retraining is added

- GPU VRAM: `8-12 GB` is a comfortable starting point for ResNet-scale experiments
- without GPU, inference is still feasible, but training becomes slow

## Main risk

The likely bottleneck is not raw compute.

The bigger risks are:

- adapting NOAA `AccessAIS` schema to the existing pipeline
- choosing a region and time range with enough valid Sentinel-2 overlap
- mapping NOAA vessel-type codes into the paper's target taxonomy cleanly
