# 05 — The `Gateway` construct

← [04 — The PyconZone construct](04-delegated-zone.md)  ·  [06 — The app services](06-app-services.md) →

**Goal:** a REST API on your delegated domain, with an ACM certificate and an
alias record, that proxies paths to HTTP backends and authenticates itself to
them with the trust store's client certificate.

**File:** [pycon2026/gateway.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/gateway.py)

## 5.1 The REST API

```python
class Gateway(Construct):
    rest_api: apigateway.RestApi

    def __init__(
        self,
        scope: Construct,
        id: str,
        zone: route53.IHostedZone | None = None,
        trust_store: TrustStore | None = None,
    ) -> None:
        super().__init__(scope, id)

        self.rest_api = apigateway.RestApi(
            self,
            "RestApi",
            # Regional, so the certificate can live in this stack's region;
            # an edge-optimised API would require one in us-east-1.
            endpoint_types=[apigateway.EndpointType.REGIONAL],
            deploy_options=apigateway.StageOptions(
                # Presented to every backend on integration requests.
                client_certificate_id=(trust_store.client_certificate_id if trust_store else None),
            ),
        )
```

**`REGIONAL` is not a style preference.** An edge-optimised API is fronted by
CloudFront, which only accepts ACM certificates from `us-east-1` — meaning a
second stack in a second region purely to hold a certificate.

**The client certificate is a stage property**, not an API or integration one:
API Gateway presents it on every integration request made by that stage. This is
the near end of the mTLS story whose far end is each service's custom domain.

**Both parameters are optional**, and each degrades cleanly:

| | with | without |
|---|---|---|
| `zone` | served on `<zone>` with an alias record | reachable only on the `execute-api` URL |
| `trust_store` | presents a client certificate to backends | backends cannot identify the caller |

So `Gateway(self, "Gateway")` is a valid, deployable, testable API.

## 5.2 The custom domain

```python
if zone is not None:
    domain = self.rest_api.add_domain_name(
        "DomainName",
        domain_name=zone.zone_name,
        certificate=acm.Certificate(
            self,
            "Certificate",
            domain_name=zone.zone_name,
            validation=acm.CertificateValidation.from_dns(zone),
        ),
        endpoint_type=apigateway.EndpointType.REGIONAL,
    )
    route53.ARecord(
        self,
        "AliasRecord",
        zone=zone,
        target=route53.RecordTarget.from_alias(route53_targets.ApiGatewayDomain(domain)),
    )
```

* **`CertificateValidation.from_dns(zone)`** hands ACM the zone, so CDK writes
  the validation record for you and renewals validate themselves forever. Give
  ACM a zone whenever you have one.
* **An alias record, not a CNAME.** Only an alias can sit at a zone apex, and
  this record is at the apex (`domain_name=zone.zone_name`).

**Deploy-time warning:** the certificate is not complete until ACM sees the
validation record, which needs step 04's delegation to have propagated. The
first deploy can sit here for several minutes.

## 5.3 Mounting backends

```python
def add_http_proxy(self, path: str, backend_url: str) -> apigateway.Resource:
    resource = self.rest_api.root.resource_for_path(path)
    # `{proxy+}` below matches sub-paths only, so the mount point itself
    # needs its own method, integrated with the backend's root.
    resource.add_method("ANY", apigateway.HttpIntegration(backend_url, http_method="ANY", proxy=True))
    resource.add_proxy(
        any_method=True,
        default_integration=apigateway.HttpIntegration(
            f"{backend_url}/{{proxy}}",
            http_method="ANY",
            proxy=True,
            options=apigateway.IntegrationOptions(
                request_parameters={"integration.request.path.proxy": "method.request.path.proxy"},
            ),
        ),
        default_method_options=apigateway.MethodOptions(
            request_parameters={"method.request.path.proxy": True},
        ),
    )
    return resource
```

**A method, not more constructor parameters.** `Gateway` takes no list of
backends; callers mount them one at a time, and the stack reads as a routing
table. This is the builder shape you see all over CDK —
`bucket.add_event_notification`, `pipeline.add_stage`. Prefer it whenever a
construct holds an open-ended collection.

**Why two integrations for one mount?** API Gateway's greedy `{proxy+}` matches
sub-paths only: `/fast/health` matches, `/fast` does not. So the mount point
gets its own `ANY` method wired to the backend root. Miss it and `/fast` returns
403 with a very unhelpful message.

**The `request_parameters` pair is a two-sided mapping**, and both sides are
required: `default_method_options` declares `method.request.path.proxy` as an
expected (required) method parameter, and `options.request_parameters` maps it
onto the integration parameter that fills the `{proxy}` placeholder. The doubled
braces in `f"{backend_url}/{{proxy}}"` emit a literal `{proxy}` for API Gateway
to substitute.

`resource_for_path` creates intermediate resources, so `add_http_proxy("a/b/c", …)`
works.

## 5.4 Use it

```python
gateway = Gateway(self, "Gateway", zone, trust_store=trust_store)
gateway.add_http_proxy("example", "https://example.com")
```

`example.com` is a deliberate first backend: it proves the routing end to end
before any of your own services exist.

## 5.5 Verify

```
$ npx cdk synth
$ uv run python -c "
import json
t = json.load(open('cdk.out/Pycon2026Stack.template.json'))
for lid, r in t['Resources'].items():
    if r['Type'] == 'AWS::ApiGateway::Resource':
        print(lid, r['Properties']['PathPart'])"
```

Expect `example` and a `{proxy+}` beneath it.

---

← [04 — The PyconZone construct](04-delegated-zone.md)  ·  [06 — The app services](06-app-services.md) →
