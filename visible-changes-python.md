# Visible changes in the Python messages (1.5.0 -> catalog wording)

Only messages whose text differs are listed. Messages not listed are word for word the same.

| Table | Key | 1.5.0 text | Catalog text |
|---|---|---|---|
| patches | empty_find | `empty FIND text` | `Empty FIND text` |
| patches | text_outside_block | `text outside a FIND/REPLACE/APPEND block` | `Text outside a FIND/REPLACE/APPEND block` |
| patches | section_no_operations | `section for {path} has no operations` | `Section for {path} has no operations` |
| patches | missing_end | `missing @@@ END` | `Missing @@@ END` |
| patches | no_sections | `no sections` | `No sections` |
| patches | unsafe_path | `unsafe patch path: {path}` | `Unsafe patch path: {path}` |
| core | config_unreadable | `cannot read config {path}: {error}` | `Cannot read config {path}: {error}` |
| core | include_empty | `include must not be empty (...)` | `Include must not be empty (...)` |
| core | too_little_room | `... for the part header and footer ...` | `... for the bite header and footer ...` |
| core | bite_header_bad | `bad or missing BITE header` | `Malformed or missing BITE header` |
| core | bite_body_short | `{path} part {i}/{n}: body shorter ...` | `{path} bite {i}/{n}: body shorter ...` |
| core | bite_footer_wrong | `{path} part {i}/{n}: footer missing ...` | `{path} bite {i}/{n}: footer missing ...` |
| core | bite_sha_mismatch | `{path} part {i}/{n}: body does not match ...` | `{path} bite {i}/{n}: body does not match ...` |
| core | bite_unreadable | `cannot read {path}: {error}` | `Cannot read {path}: {error}` |
| build | warning | `bites build: warning: {warning}` | `bites build: Warning: {warning}` |
| build | build_summary | `bites build: N chunked file(s), ...` | `bites build: N segmented file(s), ...` |
| build | bite_over_read_cap | `{file} part {i}: ...` | `{file} bite {i}: ...` |
| build | bite_over_max_chars | `{file} part {i}: chars ...` | `{file} bite {i}: chars ...` |
| build | bite_start_line_differs | `{file} part {i}: start_line ...` | `{file} bite {i}: start_line ...` |
| build | differs_from_source | `... reassembled parts differ ...` | `... reassembled bites differ ...` |
| build | orphan_bite_file | `orphan part file: {path}` | `Orphan bite file: {path}` |
| build | verify_failed | `verification failed: ...` | `Verification failed: ...` |
| build | verify_ok | `bites verify: ok, N file(s), M part(s)` | `bites verify: ok, N file(s), M bite(s)` |
| build | file_not_segmented | `{file} is not chunked in this manifest` | `{file} is not segmented in this manifest` |
| build | failure_see_log | `see the workflow run log` | `See the workflow run log` |
| cli | error_line | `bites {command}: ERROR: {message}` | `bites {command}: Error: {message}` |
| cli | description | `bites - split large text files into exact, reversible, size-capped parts.` | `bites - Segment large text files into exact, reversible, size-capped bites.` |
| cli | help_status | `on failure, write a JSON error record to this path` | `On failure, write a JSON error record to this path` |
| cli | help_toml | `the configuration file (default bites.toml); -c toml_file=FILE does the same` | `The configuration file (default bites.toml); -c toml_file=FILE does the same` |
| cli | help_config | `override a setting (...); repeat for more, ...` | `Override a setting (max_chars, read_cap, include, exclude, or toml_file); repeat for more, repeated include/exclude options add to one list` |
| cli | help_apply | `apply pending patch files` | `Apply pending patch files` |
| cli | help_src | `source repository root` | `Source repository root` |
| cli | help_patches | `patch directory, relative to --src` | `Patch directory, relative to --src` |
| cli | help_report | `write the per-section patch report (JSON) here` | `Write the per-section patch report (JSON) here` |
| cli | help_build | `write parts, manifest.json and last_build.json` | `Write bites, manifest.json and last_build.json` |
| cli | help_out | `checkout of the bites/<branch> tree` | `Checkout of the bites/<branch> tree` |
| cli | help_recorded | `recorded in the manifest` | `Recorded in the manifest` |
| cli | help_patch_report | `report written by `apply`, copied into last_build.json` | `Report written by `apply`, copied into last_build.json` |
| cli | help_full | `rebuild every large file` | `Rebuild every large file` |
| cli | help_verify | `check the output tree against the source tree` | `Check the output tree against the source tree` |
| cli | help_reassemble | `write one original file to stdout` | `Write one original file to stdout` |
| cli | help_file | `source path as listed in the manifest` | `Source path as listed in the manifest` |
| cli | help_report_failure | `turn a failure status into last_build.json` | `Turn a failure status into last_build.json` |
