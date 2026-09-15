# Validation — Orel's Nodes 0.5.0

Completed locally on 2026-09-15:

- 35 Python tests passed.
- Model downloads: existing-file reuse, duplicate requests, partial transfer handling, path containment, symlink rejection, credential precedence, collision handling, batch continuation, and queue no-op.
- Simplified schema: the model node exposes only one control input and three configuration widgets; it has no outputs. The token node has no inputs or outputs. All four node mappings are exported by one package.
- Chunked LoRA upload: uploads larger than two 512 KiB chunks, ordered offsets, size enforcement, expiry cleanup, cancellation, incomplete files, invalid safetensors, path attacks, symlinks, identical-file reuse, collision no-overwrite, and alternate registered LoRA roots.
- JavaScript harness: real DOM click/drop handlers, fixed token-node size after configure/reload, absent model outputs and removed advanced widgets, token save/remove dialog, 512 KiB upload sequence, and nested native Subgraph download-control traversal.
- Both example workflows parse. The packaged Subgraph example resolves its single external Download All control to all three internal model nodes.
- Python compilation, JavaScript syntax, and ZIP integrity checks passed.

Limits: large Hugging Face transfers remain mocked. Chunk reassembly uses real temporary files but not a live RunPod proxy. UI validation uses a DOM/LiteGraph-style harness rather than a full ComfyUI browser. The user previously confirmed the download/token UI from version 0.4 loaded, while version 0.5 still needs the live acceptance check below.

## Live acceptance

1. Remove every prior package copy, install only `orels-nodes`, restart ComfyUI, and hard-refresh.
2. Confirm all four nodes appear under one **Orel's Nodes / Models** extension.
3. Confirm Hugging Face Token has no socket and returns to a compact size after refresh.
4. Confirm Model's Download has only `download_control`, three settings, and no outputs or advanced fields.
5. Drop the same real LoRA that previously failed. Confirm visible percentage progress, final destination, the file in the LoRA directory, and loader visibility after refresh.
6. Load `examples/subgraph-download-control.json`; click Download All and verify all three internal models are detected.
