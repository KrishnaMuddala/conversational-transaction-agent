"""
Shared test fixtures.
Ensures tests run without manual env vars.
"""
import os

# Force mock parser so tests don't call Tencent ADP (which needs credentials)
os.environ.setdefault("USE_MOCK_PARSER", "true")