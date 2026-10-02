# Mozi Evals

Classify the primary business constraint in complete MoreMozi advice transcripts. Jev provides runtime classifications, and a separate baseline provides a comparison. The six labels are Focus, Leads, Sales, Offer, Retention, and People.

![A MoreMozi transcript is classified by Jev and Sol into one of six business constraints](dist/jev-sol-classification-flow.png)

## Run locally

Create the environment and download the transcript snapshot:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python eval/sync_transcripts.py
```

The corpus is saved to `data/ask-hormozi/` and excluded from Git. Use `--ref COMMIT_SHA` with the sync command to fetch a specific upstream snapshot.

Add `OPENROUTER_API_KEY` to `.env`, then start the local site:

```sh
.venv/bin/python eval/server.py
```

Open [http://127.0.0.1:8765/#classify](http://127.0.0.1:8765/#classify) and select **Run Jev**. Set `JEV_WORKERS` in `.env` to adjust concurrency (1–32; default 32). API keys stay on the local server.

To run from the terminal instead:

```sh
.venv/bin/python eval/jev_runner.py --run
```

Progress is checkpointed in `.eval-runs/jev-progress.json`; a complete run writes `dist/jev_report.json`.

## Baseline

The baseline prompt and label definitions are in `dist/baseline_spec.json`. The baseline runner uses GPT-6.1 Sol through Codex CLI:

```sh
.venv/bin/python eval/codex_baseline_runner.py --run --workers 8
```

Each transcript gets an isolated Codex session. Progress and session details are saved under `.eval-runs/`. Saved baseline results are in `dist/baseline_report.json`; its status and result count show how much of the selected set has been classified.

## Data and references

`dist/manifest.json` defines the selected cases, their order, and the selection rule. It combines curated cases with transcripts chosen from the advice screening results in `dist/advice_screen_report.json`. Hand-labeled reference cases are separate from model-generated labels. The other classifications are not ground truth.
