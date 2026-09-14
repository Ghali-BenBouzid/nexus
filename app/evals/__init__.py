"""Eval harness: a golden set, a recorder that runs it through the real pipeline,
and metrics for each stage. Run ``python -m app.evals --help``."""

import os

# Both must be set before deepeval is first imported.
# DeepEval reports usage to its developers by default; evals here stay local.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
# DeepEval also loads ./.env into os.environ on import, which would leak every
# secret in it into the whole process (and into tests). The app's settings
# already read .env themselves, so DeepEval gets nothing from it.
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")
