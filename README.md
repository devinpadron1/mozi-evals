# Eval manifest and results table

The website has two tabs: a readable HTML manifest with source video thumbnails,
and a table with one row per case, comparing baseline and grounded outputs
side by side. The styling uses Acquisition.com’s
Poppins typography, dark navy, and purple accents.

`dist/manifest.json` is the source of truth for cases, references, prompts,
framework context, judgment criteria, judge instructions and output schemas.
The Python runner consumes this manifest. GPT-6 Luna generates both prompt
variants; GPT-6 Sol judges them. Both use reasoning effort `none` and temperature 0. Ten cases × two prompts = twenty evals. The JSON remains the canonical source;
the interface presents case inputs, references and judgment criteria as HTML.
Each case has a short display summary; full evidence and rubrics are expandable.
Display summaries are not passed to either the predictor or the judge.

Run locally:

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python eval/server.py
```

Open http://127.0.0.1:8765. Configure `OPENAI_API_KEY` in the environment or a local
`.env` (ignored by Git). Click **Run evals**, or run:

```sh
.venv/bin/python eval/runner.py --run
```

A successful run writes `dist/report.json`. The hosted site shows saved results;
live runs use the local Python server. Keys never reach the browser.

The current configured account has exhausted its API credits; the GPT-6 Luna
preflight was rejected with `credit_balance_exhausted`. No completed run has been
saved. All unrun predictions, judgments and latency remain explicitly empty.

References are provisional interpretations of automatic MoreMozi captions,
with original video links. Reference advice is withheld from model inputs.
Ten selected cases and one sample per prompt demonstrate the workflow; they do not
establish general accuracy. The complete limitations are in the manifest.

Checks:

```sh
node --check dist/app.js
node --test eval/test_data.mjs
.venv/bin/python -m unittest discover -s eval -p 'test_*.py'
```
