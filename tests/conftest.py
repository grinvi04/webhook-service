import os

os.environ.setdefault("SESSION_SECRET", "test-secret-key")
os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-github-webhook-secret")
os.environ.setdefault("STRIPE_WEBHOOK_SECRET", "test-stripe-webhook-secret")
