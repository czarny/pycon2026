# 02 — The `Gateway` construct

← [01 — Initialise the project](01-init-project.md)  ·  [03 — The PyconZone construct](03-delegated-zone.md) →

**Goal:** a REST API that proxies `/example` through to `https://example.com`,
and a stack that synthesizes it.

**New file:** [pycon2026/gateway.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/gateway.py)

## What `Gateway` is

A REST API that mounts HTTP backends by path. It takes two optional
dependencies — a hosted zone and a client certificate — and each one it does not
get removes a feature and leaves the rest working, so `Gateway(self, "Gateway")`
is a valid, deployable, testable API on its `execute-api` URL. That is the
version you build here, and it is the whole construct: type the file as it
stands below.

## 2.1 The construct, in full

```python
# pycon2026/gateway.py
"""A REST API that can authenticate itself to its HTTP backends with a client certificate.

Backends are mounted with `add_http_proxy`. When a client certificate is passed
in, every request API Gateway forwards to one carries it, so the backend can
verify the caller by checking it against a trust store holding that certificate.

When a hosted zone is passed in, the API is served from that zone's domain
name, with a DNS-validated certificate and an alias record pointing at it;
otherwise it is only reachable on its execute-api URL.
"""

from aws_cdk import (
    aws_apigateway as apigateway,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
)
from constructs import Construct


class Gateway(Construct):
    rest_api: apigateway.RestApi

    def __init__(
        self,
        scope: Construct,
        id: str,
        zone: route53.IHostedZone | None = None,
        client_certificate: apigateway.CfnClientCertificate | None = None,
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
                client_certificate_id=(client_certificate.ref if client_certificate else None),
            ),
        )

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

    def add_http_proxy(self, path: str, backend_url: str) -> apigateway.Resource:
        """Mount `backend_url` at `path`, proxying every method and sub-path to it."""
        resource = self.rest_api.root.resource_for_path(path)
        # `{proxy+}` below matches sub-paths only, so the mount point itself
        # needs its own method, integrated with the backend's root.
        resource.add_method(
            "ANY",
            apigateway.HttpIntegration(
                backend_url,
                http_method="ANY",
                proxy=True,
            ),
        )
        resource.add_proxy(
            any_method=True,
            default_integration=apigateway.HttpIntegration(
                f"{backend_url}/{{proxy}}",
                http_method="ANY",
                proxy=True,
                options=apigateway.IntegrationOptions(
                    request_parameters={
                        "integration.request.path.proxy": "method.request.path.proxy",
                    },
                ),
            ),
            default_method_options=apigateway.MethodOptions(
                request_parameters={"method.request.path.proxy": True},
            ),
        )
        return resource
```

Two habits that hold for every construct in this workshop: it takes
`(scope, id, …)` and creates its resources under itself, and its **public
attributes are declared at class level** — here just `rest_api`. Anything not
declared is an implementation detail.

## 2.2 The REST API

```python
self.rest_api = apigateway.RestApi(
    self,
    "RestApi",
    endpoint_types=[apigateway.EndpointType.REGIONAL],
    deploy_options=apigateway.StageOptions(
        client_certificate_id=(client_certificate.ref if client_certificate else None),
    ),
)
```

**`REGIONAL` is not a style preference.** An edge-optimised API is fronted by
CloudFront, which only accepts ACM certificates from `us-east-1` — meaning a
second stack in a second region purely to hold a certificate. Regional keeps any
certificate this API needs in the stack's own region.

**The client certificate is a stage property**, not an API or integration one:
API Gateway presents it on every integration request made by that stage, so a
backend can identify the caller. With none passed in, the expression evaluates
to `None` and the stage presents nothing.

## 2.3 Mounting a backend

`Gateway` takes no list of backends. Callers mount them one at a time with
`add_http_proxy`, so the stack reads as a routing table. This is the builder
shape you see all over CDK — `bucket.add_event_notification`,
`pipeline.add_stage`. Prefer it whenever a construct holds an open-ended
collection.

Three things in that method are worth the read:

* **Why two integrations for one mount.** API Gateway's greedy `{proxy+}` matches
  sub-paths only: `/example/foo` matches, `/example` does not. So the mount point
  gets its own `ANY` method wired to the backend root. Miss it and `/example`
  returns 403 with a very unhelpful message.
* **The `request_parameters` pair is a two-sided mapping**, and both sides are
  required: `default_method_options` declares `method.request.path.proxy` as an
  expected method parameter, and `options.request_parameters` maps it onto the
  integration parameter that fills the `{proxy}` placeholder. The doubled braces
  in `f"{backend_url}/{{proxy}}"` emit a literal `{proxy}` for API Gateway to
  substitute.
* **`resource_for_path` creates intermediate resources**, so
  `add_http_proxy("a/b/c", …)` works.

## 2.4 The stack so far

```python
# pycon2026/stack.py
import aws_cdk as cdk
from constructs import Construct

from pycon2026.gateway import Gateway


class Stack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        gateway = Gateway(self, "Gateway")
        gateway.add_http_proxy("example", "https://example.com")
```

`example.com` is a deliberate first backend: it proves the routing end to end
before any of your own services exist, and it stays mounted for the rest of the
workshop as the one backend that is always up. It is what separates "the gateway
is broken" from "the backend is not there".

## 2.5 Verify

```
$ npx cdk synth
```

## 2.6 See it work

The stack is already deployable, and needs no DNS:

```
$ npx cdk deploy
$ curl -sS https://<rest-api-id>.execute-api.<region>.amazonaws.com/prod/example
```

The API id is in the deploy output. You get `example.com`'s homepage back
through your own API, which is the whole point of the step.

---

← [01 — Initialise the project](01-init-project.md)  ·  [03 — The PyconZone construct](03-delegated-zone.md) →
