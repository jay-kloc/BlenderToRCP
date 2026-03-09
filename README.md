# BlenderToRCP

Blender add-on to export USD/USDZ and rewrite Blender materials into Reality Composer Pro compatible MaterialX ShaderGraph graphs.

## Key features
- Export `.usda`, `.usdc`, or `.usdz` from Blender with a Reality Composer Pro friendly pipeline.
- Strict material validation: unsupported nodes fail export with copy/pasteable errors instead of silently degrading.
- RealityKit material rewrite: supported Blender shader graphs are rewritten into MaterialX graphs that Reality Composer Pro can edit.
- Portable exports: textures and auxiliary assets are staged next to the USD and rewritten to relative paths.
- Animation compatibility: actions can be concatenated for export and authored into a Reality Composer Pro animation library.
- Background Bake & Export: runs baking and export in a second Blender process, writes status/log files, and keeps the UI responsive.
- Material variants: define multiple named material sets per object and export them as USD `materialVariant` VariantSets, switchable in Reality Composer Pro.
- Shader authoring helpers: insert RealityKit PBR or Unlit node groups, browse a generated RealityKit node menu, and validate active materials in the Shader Editor.

## Important note
This is still a strict, compatibility-first exporter. Node coverage and graph translation are intentionally limited, and some Blender materials or scene setups will fail export until explicit support is added. When export succeeds, validate the result in Reality Composer Pro or with the repo validation scripts before relying on it in production.

This repo supports two workflows:
- Install the Blender add-on.
- Contribute to the add-on.

## Where to find it in Blender
- `3D View > Sidebar > RCP Exporter`: main export UI, advanced USD export settings, bake settings, job monitor, and diagnostics access.
- `3D View > Sidebar > RCP Exporter > Material Variants`: define, apply, and update material variant sets per object.
- `Shader Editor > Sidebar > RCP Exporter > RealityKit Compatibility`: validate the active material and select offending nodes.
- `Shader Editor > Sidebar > RCP Exporter > RealityKit Authoring`: insert RealityKit PBR or Unlit node groups.
- `Shader Editor > Add > RealityKit Nodes`: insert generated RealityKit node groups from the bundled node catalog.

## Install the Blender add-on
1. Download the release asset `BlenderToRCP.zip` from GitHub Releases.
2. In Blender, open `Edit > Preferences > Extensions > Add-ons > Install from Disk...`.
3. Select `BlenderToRCP.zip`.
4. Enable `BlenderToRCP` in the add-ons list.

## Contribute to the Blender add-on

### Requirements
- Blender 5.0 or newer.
- Python 3.
- Git LFS. This repo stores `.png` and `.usda` via LFS.
- OpenUSD Python bindings (`pxr`) in Blender for material rewriting and validation helpers.
- Reality Composer Pro for end-to-end validation.
- Optional command-line tools for validation:
  - `usdchecker`
  - `usdcat`
  - `xcrun realitytool`

### Local setup
1. Clone the repo and pull LFS assets:

```bash
git lfs install
git lfs pull
```

2. Ensure Blender's user extension repository exists on macOS:

```bash
mkdir -p ~/Library/Application\ Support/Blender/5.0/extensions/user_default
```

3. Symlink the add-on into Blender's extension repository:

```bash
ln -s "<path-to-this-repo>/Plugin" \
  "$HOME/Library/Application Support/Blender/5.0/extensions/user_default/BlenderToRCP"
```

4. Enable the add-on in Blender.

### Contributor quick start
Run these when you change the corresponding subsystem:

```bash
bash scripts/build_archive.sh
python3 scripts/build_materialx_manifest.py
blender --background --python scripts/build_nodegroups.py
python3 scripts/validate_nodes.py --platform xros
python3 scripts/validate_exports.py --input <export-dir-or-usd> --platform xros --deployment-target 1.0
```

Notes:
- `scripts/build_archive.sh` builds the installable archive at `dist/BlenderToRCP.zip`.
- `scripts/build_materialx_manifest.py` rebuilds `Plugin/manifest/rk_nodes_manifest.json` from `References/MaterialX-definitions`.
- `scripts/build_nodegroups.py` regenerates `Plugin/assets/nodegroups.blend`.
- `scripts/validate_nodes.py` writes generated bundles and reports under `tests/node_validation` by default and can compile each fixture with `realitytool`.
- `scripts/validate_exports.py` validates exported USD or `.rkassets` with `usdchecker`, nodedef/path lint, and optional `realitytool` compilation.

## Add-on preferences and persisted state
The add-on preferences expose:
- `USDZ Packager Path`: optional path to `usdzip`. If empty, the add-on uses the built-in Python packager.
- `MaterialX Library Path`: optional override for MaterialX definitions. If empty, the add-on uses the bundled references.
- `Default Export Format`
- `Enable Diagnostics`

The add-on also persists the last-used export settings and remembers export paths per `.blend` file. That state lives in Blender preferences, not in the repository.

## Export workflow
The main export operator validates every scene material in strict mode before writing USD. Export settings are stored on the scene and expose a large subset of Blender USD export controls, including:
- Root prim naming, selection-only export, animation export, and custom property authoring.
- Name, path, Unicode, orientation, units, and transform-op controls.
- Object-type toggles for meshes, lights, cameras, curves, points, volumes, hair, and world dome light conversion.
- Geometry and rigging controls such as UV export, `st` renaming, normals, triangulation, subdivision, armatures, deform bones, and shape keys.

If diagnostics are enabled, exports can write a `.diagnostics.json` file next to the final output and expose a `Show Diagnostics` dialog in the main panel.

## Background Bake & Export
`Bake & Export` is a background-only workflow. The add-on launches a second Blender process, bakes textures, runs the same USD export pipeline, and updates live job status in the panel.

Operational details:
- The `.blend` file must be saved before starting a background bake.
- Only one background bake/export job can run at a time.
- Job state lives under `<export_dir>/.blendertorcp_jobs/<job_id>/`.
- Each job writes `settings.json`, `status.json`, and `log.txt`.
- The panel shows progress, output path, and the current step, and supports cancel and clear actions.
- `Step Timeout (sec)` terminates the background process if a single step exceeds the configured duration.

Bake modes:
- `Unlit (Albedo)`: bakes light-independent color and rewrites the exported materials as RealityKit Unlit materials.
- `Lit (IBL baked)`: bakes the appearance under an image-based light, then still exports the final materials as RealityKit Unlit materials with the baked lighting encoded into textures.
- `Isolate Meshes (Lit)`: hides non-target meshes during lit bakes to avoid cross-mesh shadow contribution.
- `Image Format`: baked textures can be written as `.png` or `.avif`; AVIF support requires Blender 5.1+, and older builds warn and fall back to PNG.

## Material variants
Material variants let you define multiple named material configurations on a single object and export them as USD `materialVariant` VariantSets.

### Defining variants in Blender
1. Select an object that has at least one material slot.
2. Open `3D View > Sidebar > RCP Exporter > Material Variants`.
3. Click `+` to capture the current material slot assignments as a new named variant.
4. Change the object's material slots and click `+` again to create additional variants.
5. Use `Apply` to swap the object's live materials to a selected variant, or `Update` to overwrite a variant with the current slot assignments.

### How it exports
During USD export the add-on:
- Creates any variant-referenced materials that are not already on the stage.
- Places a `materialVariant` VariantSet on the parent Xform prim.
- Authors `material:binding` inside each variant via `over` on the child mesh prim.
- Clears any local `material:binding` on the mesh so the variant opinion wins (USD LIVRPS composition rules).

The first variant is selected by default. In Reality Composer Pro the variant dropdown appears on the Xform, allowing you to switch materials at authoring time or at runtime via the RealityKit API.

## Material authoring and diagnostics
BlenderToRCP is not export-only. The Shader Editor integration also supports:
- Validating the active material against the current RealityKit compatibility rules.
- Selecting offending nodes after validation.
- Inserting bundled RealityKit PBR and Unlit node groups.
- Browsing the generated RealityKit node catalog through `Add > RealityKit Nodes`.

Diagnostics workflow:
- Export-time diagnostics are gated by the `Enable Diagnostics` preference.
- The diagnostics dialog summarizes converted and failed materials, copied and converted textures, fallback nodes, KTX-required nodes, omitted nodes, and truncated warning/error lists.
- Diagnostics JSON can be inspected directly or opened in Blender's Text Editor for troubleshooting.

## Release and packaging flow
- Local packaging is script-driven through `bash scripts/build_archive.sh`.
- CI packaging is defined in `.github/workflows/build-archive.yml` and runs on manual dispatch and published releases.
- Both local and CI paths build the same archive: `dist/BlenderToRCP.zip`.

Before publishing a release, verify add-on metadata:
- `Plugin/blender_manifest.toml` still contains placeholder maintainer metadata and should be updated.
- `Plugin/__init__.py` still leaves `doc_url` empty.

## Architecture
See `docs/ARCHITECTURE.MD`.
