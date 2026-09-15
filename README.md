# Orel's Nodes — 0.5.1

One ComfyUI extension containing four nodes under **Orel's Nodes / Models**:

- **Model's Download** — downloads one Hugging Face file.
- **Download All** — starts every connected model download.
- **Hugging Face Token** — configures the shared server token.
- **LoRA Upload** — uploads local `.safetensors` files by drag and drop.

## Clean installation / update

1. Stop ComfyUI.
2. Remove every older copy of this package from `custom_nodes`. In your screenshots these are the two separate copies labeled `Orels_Nodes` and `orels-nodesv2`. Move them outside `custom_nodes` if you want a backup.
3. Extract this archive so the only package is `ComfyUI/custom_nodes/orels-nodes/__init__.py`.
4. On a first installation, run from the ComfyUI directory with its Python environment:

   ```sh
   python -m pip install -r custom_nodes/orels-nodes/requirements.txt
   ```

5. Restart ComfyUI and hard-refresh the browser (Mac: Command+Shift+R).

Version 0.5 uses new unified internal node IDs. Replace the older nodes in an existing workflow with nodes from this package, or load one of the new examples. This prevents old and new package copies from splitting ownership in the Extensions panel.

## Simplified model node

**Model's Download** has only:

- `download_control` input, used by Download All.
- `repo_id`: `owner/repository`.
- `filename`: the full path inside the Hugging Face repository, such as `split_files/vae/flux2-vae.safetensors`.
- `category`: the destination model category registered by ComfyUI.

It has no `model_path` or `status` outputs, no token input, and no `subfolder` or `revision` fields. The downloaded file uses its original basename and the default `main` revision. Status, details, and the automatically selected destination remain read-only displays.

Connect **Download All → download_models** to `download_control` on each model node. One connection can enter a native Subgraph and fan out to its model nodes. `examples/subgraph-download-control.json` demonstrates this. Queue/Run never starts downloads; press Download All or an individual Download model button.

## Hugging Face token

The token is global to this ComfyUI server, so **Hugging Face Token has no cable socket**. If `HF_TOKEN` exists in the environment of the running ComfyUI process, it is used automatically and takes priority.

Otherwise press **Set / change Hugging Face token**. Session mode lasts until restart. Remember mode stores a private-permission, unencrypted file under the ComfyUI user directory. The token is never serialized into a workflow or returned to the browser. Accept gated repository terms separately in the same Hugging Face account.

The node is forced back to a stable 460×240 size when a workflow reloads. Its dialog contains a full-width clickable button to remove saved/session credentials. An environment variable must be removed from the server environment instead.

## LoRA upload

Drop one or more `.safetensors` files into **LoRA Upload**. Version 0.5 divides each upload into 512 KiB requests, avoiding the small single-request limit that caused “Server/proxy rejected the upload” before the file reached the LoRA folder.

The server reassembles the chunks in a hidden temporary file, validates the safetensors structure, and atomically publishes it to ComfyUI's first registered `loras` path. Existing files on every registered LoRA path are checked. An identical file is reused; a different same-name file is rejected and never overwritten.

The browser must stay open during upload. An interrupted upload can be restarted by dropping the file again. Abandoned temporary uploads are cleaned when another upload starts after 24 hours. The file limit is 8 GiB. After success, refresh ComfyUI's model list/browser and select the file in the regular LoRA loader.

## Included presets

| Model | repo_id | filename | category |
|---|---|---|---|
| FLUX.2 Klein Base 9B FP8 | `black-forest-labs/FLUX.2-klein-base-9b-fp8` | `flux-2-klein-base-9b-fp8.safetensors` | `diffusion_models` |
| Qwen encoder | `Comfy-Org/vae-text-encorder-for-flux-klein-9b` | `split_files/text_encoders/qwen_3_8b_fp8mixed.safetensors` | `text_encoders` |
| FLUX.2 VAE | `Comfy-Org/flux2-dev` | `split_files/vae/flux2-vae.safetensors` | `vae` |

`examples/all-nodes.json` shows all four nodes. `examples/subgraph-download-control.json` places the three model nodes inside a Subgraph with one external Download All controller.

Downloaded models and the ComfyUI user directory should live on persistent storage in RunPod. The extension itself must also be installed in each new environment or included in the template.

See `TESTING.md` for automated coverage and live-test limits.
