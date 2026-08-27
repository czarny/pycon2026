# 07 — The `HonoApp` service, assemble and deploy

← [06 — The FastApp service](06-fast-app.md)  ·  [08 — Design notes](08-design-notes.md) →

**Goal:** the second service, the finished stack, and a deploy that proves the
whole thing end to end.

**New file:** [pycon2026/hono_app.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/hono_app.py)

## 7.1 The construct, in full

`hono_app` is a Hono (TypeScript) handler on Lambda, in
[its own repository](https://github.com/czarny/hono_app). The construct is
step 06's with a different repo name, a different docstring — and a third
variable, because this service asks for one:

| Variable | Meaning |
|---|---|
| `LABEL` | free-form string the service echoes back as the `label` key of its JSON response |

It is required, and deliberately has no default: nothing inside the construct
knows what a deployment should call itself, and the label's only reader is
someone asking *which* deployment answered — for whom a plausible wrong answer
is worse than a missing one. The stack passes its own name. `fast_app` has no
such parameter, and this is the first place the two services stop being the
same thing.

```python
# pycon2026/hono_app.py
"""The hono_app service, deployed by its own pipeline.

https://github.com/czarny/hono_app carries the application and the CDK app that
deploys it (a Hono handler on Lambda behind an HTTP API). This construct owns
neither: it stands up a pipeline that checks the repo out and runs that CDK app,
handing it the three values only this side knows —

  DOMAIN      the domain the service answers on: its subdomain of the
              delegated zone passed in
  TRUSTSTORE  the S3 URI of the trust store bundle whose client certificates its
              custom domain accepts, so only our API Gateway can reach it
              (taken from the TrustStore construct passed in)
  LABEL       free-form string the service echoes back as the "label" key of its
              JSON response, naming the deployment that owns it. Required, and
              deliberately not defaulted: nothing here knows what a deployment
              should call itself, and a wrong label is worse than an absent one
              because it is only ever read by someone asking which deployment
              answered.

All three arrive as CodeBuild environment variables, and a change to any of them
re-runs the pipeline (see CdkPipeline), so a rotated trust store is picked up on
deploy.

How the repo is built is likewise its own business: the pipeline runs the
buildspec.yml at its root.
"""

from aws_cdk import aws_route53 as route53
from constructs import Construct

from pycon2026.cdk_pipeline import CdkPipeline, SourceCode
from pycon2026.trust_store import TrustStore

#: The repo holding the application and its CDK app.
REPO_OWNER = "czarny"
REPO_NAME = "hono_app"
#: The subdomain of the delegated zone the service answers on.
SUBDOMAIN = "hono"


class HonoApp(Construct):
    #: The domain the service answers on, in the zone passed in.
    domain: str
    #: Base URL of the deployed service, for mounting behind our API.
    url: str
    #: What the service echoes back as the "label" key of its JSON response.
    label: str
    pipeline: CdkPipeline

    def __init__(
        self,
        scope: Construct,
        id: str,
        zone: route53.IHostedZone,
        trust_store: TrustStore,
        label: str,
        revision_selector: str = "main",
    ) -> None:
        super().__init__(scope, id)

        self.domain = f"{SUBDOMAIN}.{zone.zone_name}"
        self.url = f"https://{self.domain}"
        self.label = label

        self.pipeline = CdkPipeline(
            self,
            "Pipeline",
            source_code=SourceCode(
                owner=REPO_OWNER,
                repo=REPO_NAME,
                revision_selector=revision_selector,
            ),
            environment_variables={
                "DOMAIN": self.domain,
                "TRUSTSTORE": trust_store.uri,
                "LABEL": self.label,
            },
        )
```

## 7.2 Why the duplication is correct

Your first instinct will be to collapse the two files into one
`PipelineDeployedApp(repo_name=…)`. Resist it, for now.

* These files are the *seams* where the services diverge — and this one already
  has. `LABEL` goes to `hono_app` and to nothing else; in a shared
  `PipelineDeployedApp` it would be a constructor flag exactly one caller ever
  passes, which is worse than a duplicated file. The next divergence (a different
  build step, a second subdomain) lands the same way: in one file, touching one
  service.
* The duplication that matters is already factored out. Everything structural
  lives in `CdkPipeline`; what remains is a name, a subdomain and a contract.
* Each docstring documents a specific integration with a specific repository. A
  generic construct would have a generic docstring, and that knowledge would go
  somewhere worse.

Two similar files are not automatically a design flaw. Wait for the third.

## 7.3 The finished stack

```python
# pycon2026/stack.py
import aws_cdk as cdk
from constructs import Construct

from pycon2026.fast_app import FastApp
from pycon2026.gateway import Gateway
from pycon2026.hono_app import HonoApp
from pycon2026.pycon_zone import PyconZone
from pycon2026.trust_store import TrustStore


class Stack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        zone = PyconZone(self, "DelegatedZone", record_name="czarny")

        trust_store = TrustStore(self, "TrustStore")

        gateway = Gateway(self, "Gateway", zone, client_certificate=trust_store.client_certificate)
        gateway.add_http_proxy("example", "https://example.com")

        # Each deployed by its own pipeline, on its own subdomain of the
        # delegated zone, and reachable only through this API — their custom
        # domains accept just the client certificates in our trust store.
        fast_app = FastApp(self, "FastApp", zone=zone, trust_store=trust_store)
        gateway.add_http_proxy("fast", fast_app.url)

        hono_app = HonoApp(self, "HonoApp", zone=zone, trust_store=trust_store, label=self.stack_name)
        gateway.add_http_proxy("hono", hono_app.url)
```

Thirty lines, no resources, no IAM, no CloudFormation — five constructs and the
edges between them. **That is the shape a CDK stack should have.** If your stack
file grows resource declarations, it is a construct that has not been extracted
yet.

Read the edges out loud: `zone` goes to `Gateway` and to both services, each
of which derives its own subdomain of it; `trust_store` supplies the certificate
id to `Gateway` and its URI to both pipelines; each service supplies its URL back
to `Gateway`. Every arrow is one argument.

The one argument that is not an arrow is `label=self.stack_name`, and it reads
as what it is: the stack naming itself to the service it deploys.

`example.com` stays mounted deliberately: it is the one backend that works
before any pipeline has run, so it separates "the gateway is broken" from "the
service is not deployed yet".

## 7.4 Synth

```
$ npx cdk synth
```

Those 30 lines produce 66 resources.

Twelve roles and eleven policies you never wrote. That ratio is the whole
argument for CDK over hand-written CloudFormation.

`cdk.out/tree.json` holds the construct tree — your Python object graph exactly
as CDK saw it. It is the best debugging tool available when a logical id is not
what you expected.

## 7.5 Deploy

```
$ npx cdk deploy
```


Watch the first run:

```
$ aws codepipeline get-pipeline-state --name <pipeline-name>
```

## 7.6 Verify end to end

```
$ dig +short NS <you>.pycon.foo @8.8.8.8      # delegation
$ curl -sSI https://<you>.pycon.foo/example   # gateway, domain, certificate
$ curl -sS  https://<you>.pycon.foo/fast      # services, through the gateway
$ curl -sS  https://<you>.pycon.foo/hono

$ curl -sS  https://fast.<you>.pycon.foo      # must be refused
```

The `hono` response carries the label back:

```json
{"message": "Hello World", "label": "Pycon2026Stack"}
```

which is the round trip of the third variable — set here, through the pipeline,
onto the Lambda, and out again — visible in one line of output.

That last command is the one that matters. It should fail the TLS handshake —
the service's custom domain demands a client certificate from our trust store
and `curl` has none, while the identical request through the gateway succeeds
because API Gateway presents one. If the direct call *succeeds*, the service
side has not picked up `TRUSTSTORE`.

## 7.7 Tear down

```
$ npx cdk destroy
```

The trust store bucket empties itself and the log groups go with the stack —
both settings chosen for exactly this moment. The two *service* stacks were
deployed by the pipelines, not by this stack, so destroy them from their own
repositories.

---

← [06 — The FastApp service](06-fast-app.md)  ·  [08 — Design notes](08-design-notes.md) →
