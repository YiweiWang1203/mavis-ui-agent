# Main video UI path

The normal `scripts/run_video_ui_workflow.py --video ... --prompt ... --output ... --run-id ...` entry now uses `config/main_ui.json`. It runs fresh local ASR, frame selection, preprocessing, and the shared `vision_node`, `ui_architect_node`, `code_node` in a fixed LangGraph followed by local artifact/structure review. ASR is enabled by configuration. No frozen visual JSON or manual interaction groups are accepted by this path.

The UI nodes still serve the existing full coordinator graph. API upload/full-agent routing is a separate entry and has not been end-to-end validated by the eight-video batch. Do not describe this CLI test as an API upload test or local review as semantic/browser acceptance. The historical `--full-graph` / `--legacy-pipeline` route is explicitly separate and is not the bounded main-video batch.

Default provider: existing SiliconFlow credentials in the project `.env`; vision, architect and Coder use Qwen/Qwen3-VL-32B-Instruct, 8192 output tokens, 600 seconds and zero SDK/HTTP retries. Preserve the original conditional vision correction (at most once) with an explicit trigger record. Maximum four physical requests per video. A provider error consumes the slot and stops further requests. No Coder request after an invalid vision or architect return.

ASR reads four verified existing local model directories from `config/asr_model_identity.json`; no dependency installation/download is performed. `pred_timestamp=True` repairs the previously demonstrated producer/consumer timestamp mismatch; it is not evidence of ASR accuracy.

Source alignment accepts conservative reciprocal type/text/geometry evidence and retains unresolved objects. Target geometry preservation is enabled. Invalid geometry is recorded without inventing replacements and forwarded with an unresolved diagnostic in this main configuration; it is not marked geometrically passed. Experimental hierarchy/relationship gates, consumer projection and manually annotated FUNCTIONAL groups remain off.

Coder gets the original request and fresh ASR in addition to the existing UI-State. The native-control contract and general implementation contract do not inject case-specific requirements. Display objects are not automatically business-click targets. This is a generation instruction, not proof of the resulting behavior.

New HTML is written by the real `save_html_asset` into `data/outputs/html_code/<run-id>/html_generated_<timestamp>.html`, with a source manifest. Nothing copies an old page into this directory. Node inputs/outputs, raw model responses and usage, traces, terminal state, source/input identities and artifact hashes live under the requested output/run-id directory. Failure diagnostics redact known credential environment values. Missing cost remains unknown.

Source base:494199e. This is not a descendant of3b5735a; merge-base is63b9b86. Comparing the src trees shows only the preserve-target changes in architect/layout_solver;3b5735a only recorded the prior feedback result. Previous production prompts/configuration must be backed up before deploying the integration branch into the main project. Do not overwrite preexisting dirty changes or merge experiments by timestamp.
