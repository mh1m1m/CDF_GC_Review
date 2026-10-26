"""OpenAI Responses API through the official SDK; no consumer-token reuse."""

from ..contracts import MODE_LIVE, TokenUsage
from ..provenance import official_endpoint
from .base import ProviderAdapter, ProviderFailure, ProviderResult


class OpenAIAdapter(ProviderAdapter):
    name = "openai"
    mode = MODE_LIVE
    endpoint = official_endpoint("openai")

    def __init__(self, config=None, client=None, api_key=None):
        super().__init__(config)
        self._client = client
        self._api_key = api_key or None                # a key saved in the AI settings; else the SDK reads the env
        self.client_injected = client is not None

    def complete(self, request):
        import openai

        try:
            extra = {"api_key": self._api_key} if self._api_key else {}
            client = self._client or openai.OpenAI(
                base_url=self.endpoint,  # pinned: OPENAI_BASE_URL never redirects a trusted adapter
                timeout=self.config.timeout_seconds, max_retries=self.config.max_retries, **extra
            )
            self._client = client
            response = client.responses.create(
                model=request.model or self.model,
                instructions=request.system,
                input=request.user_text,
                max_output_tokens=request.max_tokens,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "cdf_" + request.role.lower(),
                        "strict": True,
                        "schema": request.schema,
                    }
                },
                store=False,
            )
        except openai.AuthenticationError as exc:
            raise ProviderFailure(
                "OpenAI authentication rejected", kind="AUTHENTICATION"
            ) from exc
        except openai.PermissionDeniedError as exc:
            raise ProviderFailure(
                "OpenAI permission rejected", kind="PERMISSION"
            ) from exc
        except openai.APITimeoutError as exc:
            raise ProviderFailure("OpenAI request timed out", kind="TIMEOUT") from exc
        except openai.APIConnectionError as exc:
            raise ProviderFailure(
                "OpenAI connection unavailable", kind="CONNECTION"
            ) from exc
        except openai.APIStatusError as exc:
            raise ProviderFailure(
                "OpenAI HTTP failure " + str(exc.status_code), kind="API_STATUS"
            ) from exc
        except Exception as exc:
            raise ProviderFailure(
                "OpenAI SDK request unavailable", kind="SDK_OR_CONFIGURATION"
            ) from exc
        if getattr(response, "status", None) != "completed":
            raise ProviderFailure("OpenAI response incomplete", kind="INCOMPLETE")
        if not response.id or not getattr(response, "_request_id", None):
            raise ProviderFailure(
                "Provider receipt missing", kind="PROVIDER_RECEIPT_MISSING"
            )
        usage = response.usage
        return ProviderResult(
            response.output_text,
            response.id,
            response.model,
            TokenUsage(int(usage.input_tokens), int(usage.output_tokens)),
            provider_request_id=getattr(response, "_request_id", None),
        )
