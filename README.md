# Constraint — Advisor workspace

A custom website for preparing a business-constraint consultation and inspecting
baseline vs framework-grounded OpenAI outputs. Vanilla HTML/CSS/JavaScript,
with a small Python runner and local HTTP server. No evaluation-platform account
is required.

## Run locally

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python eval/server.py
```

Open http://127.0.0.1:8765. The website works immediately with source-derived
reference briefs. These are explicitly labeled as consultation references,
not model outputs.

Set `OPENAI_API_KEY` in your environment or copy `.env.example` to `.env`
and enter your key locally. `.env` files are ignored by Git and never served.
You can also use `eval/server.py --env-file /absolute/path/to/.env`.

Use **Evaluations → Run evaluation** locally, or:

```sh
.venv/bin/python eval/runner.py --run
```

The runner generates six structured outputs (three cases × two prompts), checks
source IDs, and grades each output with an OpenAI structured judge. It writes
`dist/report.json` only after all six outputs and grades succeed. The previous
run survives a failed rerun. Export/import controls move saved runs between the
local website and hosted website. Model calls use the configured account and
incur its API charges. The local server binds to loopback only.

## What is deployed

The hosted website is static and private by default. It displays saved runs and
supports advisor reviews and JSON export/import. API keys are never embedded in
the site. Live model reruns require the local server. Browser reviews are local
to that browser and origin; exporting is required to move them to another device.

## Sources and evaluation limits

- Cases are paraphrases of three MoreMozi consultation transcripts from the
  community [ask-hormozi corpus](https://github.com/poseljacob/ask-hormozi).
  Each case links to the original video, source windows and transcript.
- Captions may be wrong. Reference labels reflect analyst interpretation and
  need independent expert review. They are not an official Acquisition.com taxonomy.
- Some owner statements were made after the consultation began. This is not a
  prospective test from the opening question alone.
- Reference answers and consultation videos are excluded from both model prompts
  and the supplied context. Unknown pretraining exposure is not controlled.
- Grounded context is three fixed, paraphrased Scaling Roadmap notes. There is
  no automated retrieval and no fine-tuning.
- Schema and source validity are code checks. Exact label match is a code metric.
  The other three scores are model judgments. The complete rubric is visible.
- The target and judge default to the same model snapshot; judge independence
  and agreement with human reviewers need further work.
- Three cases, one sample each, demonstrate a workflow. They do not establish
  general accuracy, prompt superiority or business outcomes.
- Latency measures the inference request, parsing and retries, excluding grading.
  Token usage is recorded; no unverified dollar-cost estimate is shown.
- No model outputs or scores are fabricated. If API credit is unavailable,
  the evaluation page remains explicitly pending.

## Files

- `dist/app.js`, `dist/style.css`: custom interface.
- `dist/cases.json`: owner facts, provenance and withheld references.
- `dist/prompts.json`: both prompts, taxonomy and fixed context.
- `eval/runner.py`: OpenAI generation and custom evaluation.
- `eval/server.py`: local website and rerun endpoint.
- `eval/test_runner.py`: meaningful validation checks, without network requests.

## Checks

```sh
node --check dist/app.js
.venv/bin/python -m unittest discover -s eval -p 'test_*.py'
```
