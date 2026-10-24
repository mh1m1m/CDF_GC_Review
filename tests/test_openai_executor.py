"""Injected SDK fixtures never count as verified provider inference."""
from types import SimpleNamespace
import json
import pytest
from cdf_gco_crms.agents.providers.openai_adapter import OpenAIAdapter
from cdf_gco_crms.agents.providers.base import ProviderConfig,ProviderFailure
from cdf_gco_crms.agents import contracts as C, provenance as P
from cdf_gco_crms.agents.runner import AgentRunner


def test_official_openai_contract_disables_storage_and_injected_client_is_untrusted():
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(status='completed',id='fixture-response',_request_id='fixture-request',model='fixture-model',
            output_text=json.dumps({'observations':[],'gaps_not_drafted':[],'reasoning_summary':'SYNTHETIC SDK CONTRACT TEST'}),
            usage=SimpleNamespace(input_tokens=1,output_tokens=2))
    adapter=OpenAIAdapter(ProviderConfig(model='fixture-model',max_retries=0),client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    response=AgentRunner(adapter,max_attempts=1).run(C.ROLE_DRAFTING,'Synthetic schema validation',{'label':'SYNTHETIC','case_id':'SYN-SDK'})
    assert response.ok and not response.is_live and response.execution_source==P.SOURCE_PROVIDER_API_UNTRUSTED
    assert calls[0]['store'] is False and calls[0]['text']['format']['strict'] is True


@pytest.mark.parametrize('status,receipt,expected',[('incomplete','fixture-request','INCOMPLETE'),('completed',None,'PROVIDER_RECEIPT_MISSING')])
def test_openai_missing_completion_or_receipt_fails(status,receipt,expected):
    from cdf_gco_crms.agents.contracts import AgentRequest
    response=SimpleNamespace(status=status,id='fixture-response',_request_id=receipt)
    adapter=OpenAIAdapter(client=SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs:response)))
    request=SimpleNamespace(model='fixture-model',system='SYNTHETIC',user_text='SYNTHETIC',max_tokens=10,role='DRAFTING',schema={})
    with pytest.raises(ProviderFailure) as error:adapter.complete(request)
    assert error.value.kind==expected


def test_anthropic_sdk_error_body_is_not_persistable_provider_error():
    import anthropic,httpx
    from cdf_gco_crms.agents.providers.anthropic_adapter import AnthropicAdapter
    marker='SYNTHETIC_ERROR_BODY_MUST_NOT_ESCAPE'
    def reject(**kwargs):raise anthropic.AuthenticationError(marker,response=httpx.Response(401,request=httpx.Request('POST','https://example.invalid/messages')),body={'error':marker})
    adapter=AnthropicAdapter(client=SimpleNamespace(messages=SimpleNamespace(with_raw_response=SimpleNamespace(create=reject))))
    request=SimpleNamespace(model='fixture-model',max_tokens=10,system='SYNTHETIC',user_text='SYNTHETIC',schema={})
    with pytest.raises(ProviderFailure) as error:adapter.complete(request)
    assert error.value.kind=='AUTHENTICATION' and marker not in str(error.value)
