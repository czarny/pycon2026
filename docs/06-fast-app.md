# 06 — The `FastApp` service

← [05 — The TrustStore construct](05-trust-store.md)  ·  [07 — The HonoApp service, assemble and deploy](07-hono-app.md) →

**Goal:** a service construct that stands up a pipeline deploying a *different
repository's* CDK app, handed the domain and the trust store from this side, and
mounted behind our gateway at `/fast`.

**New file:** [pycon2026/fast_app.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/fast_app.py)

## The idea

`fast_app` is a FastAPI service on Lambda, living in
[its own repository](https://github.com/czarny/fast_app) with its own CDK app,
dependencies, release cadence and `buildspec.yml`. **This stack owns none of
that.** It owns the pipeline that deploys the repo, and the two facts a service
cannot know about itself:

| Variable | Meaning |
|---|---|
| `DOMAIN` | the domain the service answers on, inside our delegated zone |
| `TRUSTSTORE` | the S3 URI of the bundle whose client certificates its custom domain must accept |

Both arrive as CodeBuild environment variables. That is the entire interface
between the platform repo and a service repo — two strings.

This is the split the workshop is really about. Most CDK tutorials build one app
in one repository; here you are building the platform that other teams deploy
into.

## 6.1 The construct, in full

```python
# pycon2026/fast_app.py
"""The fast_app FastAPI service, deployed by its own pipeline.

https://github.com/czarny/fast_app carries the application and the CDK app that
deploys it (a Lambda behind an HTTP API). This construct owns neither: it stands
up a pipeline that checks the repo out and runs that CDK app, handing it the two
values only this side knows —

  DOMAIN      the domain the service answers on, in our delegated zone
  TRUSTSTORE  the S3 URI of the trust store bundle whose client certificates its
              custom domain accepts, so only our API Gateway can reach it
              (taken from the TrustStore construct passed in)

Both arrive as CodeBuild environment variables, and a change to either re-runs
the pipeline (see CdkPipeline), so a rotated trust store is picked up on deploy.

How the repo is built is likewise its own business: the pipeline runs the
buildspec.yml at its root.
"""

from constructs import Construct

from pycon2026.cdk_pipeline import CdkPipeline, SourceCode
from pycon2026.trust_store import TrustStore

#: The repo holding the application and its CDK app.
REPO_OWNER = "czarny"
REPO_NAME = "fast_app"


class FastApp(Construct):
    #: Base URL of the deployed service, for mounting behind our API.
    url: str
    pipeline: CdkPipeline

    def __init__(
        self,
        scope: Construct,
        id: str,
        domain: str,
        trust_store: TrustStore,
        revision_selector: str = "main",
    ) -> None:
        super().__init__(scope, id)

        self.url = f"https://{domain}"

        self.pipeline = CdkPipeline(
            self,
            "Pipeline",
            source_code=SourceCode(
                owner=REPO_OWNER,
                repo=REPO_NAME,
                revision_selector=revision_selector,
            ),
            environment_variables={
                "DOMAIN": domain,
                "TRUSTSTORE": trust_store.uri,
            },
        )
```

That is the whole construct — about forty lines including its docstring
Everything structural was already paid for in step 04; what is left is 
a repo name, a domain and a contract.

## 6.2 `revision_selector` and releases

The default `"main"` deploys every push. Pin a service to releases by passing a
version tag instead:

```python
FastApp(self, "FastApp", domain=..., trust_store=trust_store, revision_selector="v1.2.0")
```

Step 4.3 turns that into a tag-triggered pipeline automatically, because the
string matches `TAG_VERSION_PATTERN`. Nothing else changes — no flag, no second
code path in this file.

## 6.3 The far end of the mTLS story

The service repo's CDK app reads `TRUSTSTORE`, parses it, and configures its API
Gateway custom domain with `mutual_tls_authentication` pointing at that bucket,
key and version. From then on the service's public domain refuses any request
not carrying a certificate from our bundle — that is, any request that did not
come through our `Gateway`.

Walk the whole chain once, because it is the payoff of steps 02, 04, 05 and 06
together:

1. `TrustStore` issues a client certificate and writes its PEM to a **versioned**
   S3 object.
2. `trust_store.uri` carries bucket + key + **version**.
3. `FastApp` passes that URI to its pipeline as `TRUSTSTORE`.
4. `CdkPipeline` tags the pipeline with a digest of the value, and re-runs on
   update.
5. `Gateway`'s stage presents the matching certificate on every integration
   request.
6. On 1 January or 1 July the rotation suffix in the logical id changes: a new
   certificate is issued, the bundle rewritten, its version id changed, the tag
   changed, the pipeline re-run — and the service starts trusting the new
   certificate while the gateway starts presenting it.

Certificate rotation across two repositories, expressed as one date-derived
logical id and one tag.

## 6.4 The stack so far

```python
# pycon2026/stack.py
import aws_cdk as cdk
from constructs import Construct

from pycon2026.fast_app import FastApp
from pycon2026.gateway import Gateway
from pycon2026.pycon_zone import PyconZone
from pycon2026.trust_store import TrustStore


class Stack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        zone = PyconZone(self, "DelegatedZone", record_name="czarny")

        trust_store = TrustStore(self, "TrustStore")

        gateway = Gateway(self, "Gateway", zone, client_certificate=trust_store.client_certificate)
        gateway.add_http_proxy("example", "https://example.com")

        # Deployed by its own pipeline, on its own subdomain of the delegated
        # zone, and reachable only through this API — its custom domain accepts
        # just the client certificates in our trust store.
        fast_app = FastApp(
            self,
            "FastApp",
            domain=f"fast.{zone.zone_name}",
            trust_store=trust_store,
        )
        gateway.add_http_proxy("fast", fast_app.url)
```


## 6.5 Verify

```
$ npx cdk synth
```

---

← [05 — The TrustStore construct](05-trust-store.md)  ·  [07 — The HonoApp service, assemble and deploy](07-hono-app.md) →
