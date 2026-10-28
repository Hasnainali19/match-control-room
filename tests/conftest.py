import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for k in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT", "GITHUB_TOKEN", "GITHUB_MODELS_TOKEN"):
    os.environ.pop(k, None)  # tests always run in deterministic offline mode
