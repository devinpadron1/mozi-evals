# Eval manifest and results table

The website has two sections: the complete JSON evaluation manifest and a table
of all case/prompt evaluations. No advisor workspace or review workflow.

`dist/manifest.json` is the source of truth for cases, references, prompts,
framework context, judgment criteria, judge instructions and output schemas.
The Python runner consumes this manifest. Three cases × two prompts = six evals.

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

The current configured account has exhausted its API credits. All unrun
predictions, judgments and latency remain explicitly empty.

References are provisional interpretations of automatic MoreMozi captions,
with original video links. Reference advice is withheld from model inputs.
Three cases and one sample per prompt demonstrate the workflow; they do not
establish general accuracy. The complete limitations are in the manifest.

Checks:

```sh
node --check dist/app.js
.venv/bin/python -m unittest discover -s eval -p 'test_*.py'
```
