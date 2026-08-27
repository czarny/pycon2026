# 06 — The app services: `FastApp` and `HonoApp`

← [05 — The Gateway construct](05-gateway.md)  ·  [07 — Assemble and deploy](07-assemble-and-deploy.md) →

**Goal:** two service constructs, each standing up a pipeline that deploys a
*different repository's* CDK app, handed the domain and the trust store from
this side.

**Files:** [pycon2026/fast_app.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/fast_app.py),
[pycon2026/hono_app.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/hono_app.py)

## The idea

`fast_app` is a FastAPI service on Lambda; `hono_app` is a Hono (TypeScript)
handler on Lambda. Each lives in its own repository with its own CDK app,
dependencies, release cadence and `buildspec.yml`. **This stack owns neither.**
It owns the pipeline that deploys them, and the two facts a service cannot know
about itself:

| Variable | Meaning |
|---|---|
| `DOMAIN` | the domain the service answers on, inside our delegated zone |
| `TRUSTSTORE` | the S3 URI of the bundle whose client certificates its custom domain must accept |

Both arrive as CodeBuild environment variables. That is the entire interface
between the platform repo and a service repo — two strings.

## 6.1 The construct

```python
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

That is the whole construct — about forty lines including its docstring, and
most of it is the docstring. `HonoApp` is the same with
`REPO_NAME = "hono_app"`. Copy it.

## 6.2 Why the duplication is correct

Your first instinct will be to collapse the two files into one
`PipelineDeployedApp(repo_name=…)`. Resist it, for now.

* These files are the *seams* where the services will diverge. The moment
  `hono_app` needs a second environment variable or a different build step, the
  shared abstraction sprouts a flag — and a flag only one caller passes is worse
  than a duplicated file.
* The duplication that matters is already factored out. Everything structural
  lives in `CdkPipeline`; what remains is a name, a domain and a contract.
* Each docstring documents a specific integration with a specific repository. A
  generic construct would have a generic docstring, and that knowledge would go
  somewhere worse.

Two similar files are not automatically a design flaw. Wait for the third.

## 6.3 `revision_selector` and releases

The default `"main"` deploys every push. Pin a service to releases by passing a
version tag instead:

```python
FastApp(self, "FastApp", domain=..., trust_store=trust_store, revision_selector="v1.2.0")
```

Step 02.2 turns that into a tag-triggered pipeline automatically, because the
string matches `TAG_VERSION_PATTERN`. Nothing else changes.

## 6.4 The far end of the mTLS story

The service repo's CDK app reads `TRUSTSTORE`, parses it, and configures its API
Gateway custom domain with `mutual_tls_authentication` pointing at that bucket,
key and version. From then on the service's public domain refuses any request
not carrying a certificate from our bundle — that is, any request that did not
come through our `Gateway`.

Walk the whole chain once, because this is the payoff of steps 02, 03 and 06
together:

1. `TrustStore` issues a client certificate and writes its PEM to a **versioned**
   S3 object.
2. `trust_store.uri` carries bucket + key + **version**.
3. `FastApp` passes that URI to its pipeline as `TRUSTSTORE`.
4. `CdkPipeline` tags the pipeline with a digest of the value, and re-runs on
   update.
5. On 1 January or 1 July the rotation suffix in the logical id changes, a new
   certificate is issued, the bundle is rewritten, its version id changes, both
   tags change, **both pipelines re-run**, and both services start trusting the
   new certificate — while `Gateway`'s stage starts presenting it.

Certificate rotation across three repositories, expressed as one date-derived
logical id and one tag.

## 6.5 Verify

```
$ npx aws-cdk synth
$ uv run python -c "
import json
t = json.load(open('cdk.out/Pycon2026Stack.template.json'))
for lid, r in t['Resources'].items():
    if r['Type'] == 'AWS::CodePipeline::Pipeline':
        print(lid, [tag['Key'] for tag in r['Properties'].get('Tags', [])])"
```

Two pipelines, each tagged `ENV.DOMAIN` and `ENV.TRUSTSTORE`.

---

← [05 — The Gateway construct](05-gateway.md)  ·  [07 — Assemble and deploy](07-assemble-and-deploy.md) →
