import hashlib
import hmac
import logging

from fastapi import Depends, HTTPException, Request, status

from .config import settings

logger = logging.getLogger(__name__)

class WebhookVerifier:
    """
    A generic webhook signature verifier that can be configured for different providers.
    """
    def __init__(self, source: str):
        self.source = source

    async def __call__(self, request: Request):
        body = await request.body()

        if self.source == "github":
            await self._verify_github(request, body)
        elif self.source == "stripe":
            await self._verify_stripe(request, body)
        else:
            logger.error(f"Verifier for source '{self.source}' is not implemented.")
            raise HTTPException(status_code=501, detail=f"Verifier for source '{self.source}' is not implemented.")

    async def _verify_github(self, request: Request, body: bytes):
        secret = settings.github_webhook_secret.encode('utf-8')
        signature_header = request.headers.get('x-hub-signature-256')
        
        if not signature_header:
            raise HTTPException(status_code=400, detail="X-Hub-Signature-256 header is missing.")

        signature = hmac.new(secret, body, hashlib.sha256).hexdigest()
        expected_signature = f"sha256={signature}"

        if not hmac.compare_digest(expected_signature, signature_header):
            raise HTTPException(status_code=401, detail="Invalid GitHub signature.")

    async def _verify_stripe(self, request: Request, body: bytes):
        # Stripe's verification is more involved and uses its own library.
        # For this example, we'll show the conceptual structure.
        # In a real project, you would `pip install stripe` and use `stripe.Webhook.construct_event`
        secret = settings.stripe_webhook_secret
        signature_header = request.headers.get('stripe-signature')

        if not signature_header:
            raise HTTPException(status_code=400, detail="Stripe-Signature header is missing.")
        
        # Conceptual check. The actual implementation is more complex.
        # try:
        #     event = stripe.Webhook.construct_event(
        #         payload=body, sig_header=signature_header, secret=secret
        #     )
        # except ValueError as e: # Invalid payload
        #     raise HTTPException(status_code=400, detail=str(e))
        # except stripe.error.SignatureVerificationError as e: # Invalid signature
        #     raise HTTPException(status_code=401, detail=str(e))
        
        logger.warning("Stripe verification is a placeholder. Implement with the official Stripe library.")
        pass # Placeholder for actual Stripe verification logic

# Create an instance for each provider
verify_github = WebhookVerifier(source="github")
verify_stripe = WebhookVerifier(source="stripe")