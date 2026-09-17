import os

# pytest loads this before the test modules, and some of them import deepeval
# directly (third-party imports sort before app ones), ahead of the same guard in
# app/evals/__init__.py. Without it, deepeval loads ./.env into os.environ on
# import and leaks its secrets into every other test in the run.
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
