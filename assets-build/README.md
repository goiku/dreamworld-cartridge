# Building the browser client

The top-level installer runs this step after preparing the pinned website and assets and applying the server source changes. To repeat the asset build in an existing installation:

```sh
uv run --no-project --python 3.13 --with pillow==13.0.0 --with fonttools==4.68.0 python assets-build/build.py /path/to/runtime
```

The input mirror comes from [dreamworld-assets at 6e0550d](https://github.com/minibug1021/dreamworld-assets/tree/6e0550dab8552cd54bd976d4023f9ec0c43f6d7c). The `dreamworld_assets` folder belongs under the runtime root. Both the originally archived localized files and the `shared.pokemon-gl.com` directory are required.

* **Web pages and strings.** `text-manifest.json` names the archived source for each change. Each entry in `edits/` gives a start and end character offset and the replacement text in the corresponding UTF-8 source, using LF line endings. Base and result hashes check the edits. New standalone pages and styles are in `new/`. The Korean report recipe reuses the archived Korean navigation and Japanese report.
* **Chinese client.** The recipes translate embedded game strings and typeset the original buttons, instructions and menus. FontTools reads Noto Sans SC to add missing glyphs to the archived Flash fonts. The report and opening recipes use Pillow to draw the localized text. The builder uses Windows' Noto Sans SC variable font when present. On other installations it retrieves the pinned [Google Fonts copy](https://github.com/google/fonts/tree/a85815a42757630ce188fdad368c2dfc444d4773/ofl/notosanssc), verified against its Git object ID. Pass `--font PATH` to use a local Noto Sans SC variable TrueType font. Its SIL Open Font License travels with the font recipe and the generated client.
* **Dream Island and home client.** The editable ActionScript substitutions are in the server source patch (`utils/patching/swf_patches.py` in the installed tree). Two small BSDIFF40 files reproduce the tested compiled changes from the corresponding original SWF bodies. SHA-256 checks on both decompressed inputs and results allow different zlib compression levels. The runtime's other prebuilt patches come from the pinned web project.
* **Flash player.** The builder retrieves the [Ruffle 0.7.1 self-hosted web ZIP](https://github.com/ruffle-rs/ruffle/releases/tag/v0.7.1), verifies its SHA-256 and installs its files and license texts locally. Pass `--ruffle-archive PATH` to reuse a downloaded ZIP.
