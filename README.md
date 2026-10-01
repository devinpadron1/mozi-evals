# Eval manifest and results table

The website has two tabs: a readable HTML manifest with source video thumbnails,
and a table with one row per case, comparing baseline and grounded outputs
side by side. The styling uses Acquisition.com’s
Poppins typography, dark navy, and purple accents.

`dist/manifest.json` is the source of truth for cases, references, prompts,
framework context, judgment criteria, judge instructions and output schemas.
The Python runner consumes this manifest. GPT-5.6 Luna generates both prompt
variants; GPT-5.6 Sol judges them. Both use reasoning effort `none` and default sampling. Ten cases × two prompts = twenty evals. The JSON remains the canonical source;
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

### Use your ChatGPT plan locally

Eligible accounts can authorize this personal local runner through the official
Sign in with ChatGPT flow:

```sh
npm ci --prefix eval/chatgpt
npm run build --prefix eval/chatgpt
node eval/chatgpt/bridge.mjs sign-in
.venv/bin/python eval/runner.py --run --auth chatgpt --model gpt-5.6-luna --judge-model gpt-5.6-sol
```

For the local website run `.venv/bin/python eval/server.py --auth chatgpt`.
Model availability is checked against the signed-in account before inference;
unavailable models cause a clear error and are never substituted. Updating the
manifest is required before displaying results from a different model pair.

The local Node process owns OAuth, verified identity, token refresh and streaming
inference. Connection data is encrypted with AES-256-GCM using a random key kept
in macOS Keychain, under `~/Library/Application Support/Mozi Evals/ChatGPT`.
Credentials never enter the Python process, browser, repository or published
site. Only completed, schema-validated responses can become saved results.
Manage plan usage at https://chatgpt.com/settings/usage.

The supported local DevKit is pinned and vendored with its license in
`eval/chatgpt/vendor`; the small documented extension adds structured output and
terminal response metadata. The plan route does not support temperature or
output-token-limit overrides, so these fields are omitted. This adapter currently requires macOS.

The October 1 run completed seven output-and-judge pairs before ChatGPT returned
`subscription_sharing_usage_limit_exceeded`. The user requested stopping there.
The earlier runner wrote only at full-run completion, so those seven outputs and
scores were not retained and no report is published. The runner now checkpoints
each validated prediction and judgment into ignored `.eval-runs/`; add `--resume`
to continue a compatible interrupted run without repeating saved work. A complete
report replaces `dist/report.json` only after all twenty evaluations succeed.

References are provisional interpretations of automatic MoreMozi captions,
with original video links. Reference advice is withheld from model inputs.
Ten selected cases and one sample per prompt demonstrate the workflow; they do not
establish general accuracy. The complete limitations are in the manifest.

Checks:

```sh
npm test --prefix eval/chatgpt
node --check dist/app.js
node --test eval/test_data.mjs
.venv/bin/python -m unittest discover -s eval -p 'test_*.py'
```
