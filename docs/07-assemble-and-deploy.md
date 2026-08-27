# 07 — Assemble and deploy

← [06 — The app services](06-app-services.md)  ·  [08 — Design notes](08-design-notes.md) →

**Goal:** wire the five constructs into one stack, synthesize it, deploy it, and
prove it works end to end.

**File:** [pycon2026/stack.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/stack.py)

## 7.1 The wiring diagram

```python
class Stack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        zone = PyconZone(self, "DelegatedZone", record_name="czarny")

        trust_store = TrustStore(self, "TrustStore")

        gateway = Gateway(self, "Gateway", zone, trust_store=trust_store)
        gateway.add_http_proxy("example", "https://example.com")

        # Each deployed by its own pipeline, on its own subdomain of the
        # delegated zone, and reachable only through this API — their custom
        # domains accept just the client certificates in our trust store.
        fast_app = FastApp(
            self,
            "FastApp",
            domain=f"fast.{zone.zone_name}",
            trust_store=trust_store,
        )
        gateway.add_http_proxy("fast", fast_app.url)

        hono_app = HonoApp(
            self,
            "HonoApp",
            domain=f"hono.{zone.zone_name}",
            trust_store=trust_store,
        )
        gateway.add_http_proxy("hono", hono_app.url)
```

Thirty lines, no resources, no IAM, no CloudFormation — five constructs and the
edges between them. **That is the shape a CDK stack should have.** If your stack
file grows resource declarations, it is a construct that has not been extracted
yet.

Read the edges out loud: `zone` supplies its name to `Gateway` and to both
service domains; `trust_store` supplies the certificate id to `Gateway` and its
URI to both pipelines; each service supplies its URL back to `Gateway`. Every
arrow is one argument.

`example.com` stays mounted deliberately: it is the one backend that works
before any pipeline has run, so it separates "the gateway is broken" from "the
service is not deployed yet".

## 7.2 Synth

```
$ uv run black --check .
$ uv run pytest
$ npx cdk synth
```

Those 30 lines produce 66 resources:

```
$ uv run python -c "
import json, collections
t = json.load(open('cdk.out/Pycon2026Stack.template.json'))
for typ, n in sorted(collections.Counter(r['Type'] for r in t['Resources'].values()).items()):
    print(f'{n:3} {typ}')"
```

Twelve roles and eleven policies you never wrote. That ratio is the whole
argument for CDK over hand-written CloudFormation.

`cdk.out/tree.json` holds the construct tree — your Python object graph exactly
as CDK saw it. It is the best debugging tool available when a logical id is not
what you expected.

## 7.3 Deploy

You need credentials now, and a bootstrapped account.

```
$ npx cdk diff
$ npx cdk deploy
```

Roughly in order:

1. **The hosted zone and its delegation.** If your account is not on the parent
   role's trust policy, this fails with `AccessDenied` on `sts:AssumeRole`.
2. **The client certificate, bucket and builder** — quick.
3. **The ACM certificate**, which blocks until DNS validation succeeds. **This
   is the slow step: several minutes is normal.** Past ~15 minutes, check
   `dig +short NS <you>.pycon.foo`.
4. **The API, domain name and alias record.**
5. **The two pipelines**, which start running as soon as they are created.

Watch the first run:

```
$ aws codepipeline get-pipeline-state --name <pipeline-name>
```

The most common failure is the **CodeConnections connection still `PENDING`** —
it cannot be authorised from the CLI. Fix it in the console (Developer Tools →
Settings → Connections) and `aws codepipeline start-pipeline-execution`. Second
most common: the source repo has no `buildspec.yml` at its root, or its
`cdk deploy` cannot assume the `cdk-*` roles because that account was never
bootstrapped.

## 7.4 Verify end to end

```
$ dig +short NS <you>.pycon.foo @8.8.8.8      # delegation
$ curl -sSI https://<you>.pycon.foo/example   # gateway, domain, certificate
$ curl -sS  https://<you>.pycon.foo/fast      # services, through the gateway
$ curl -sS  https://<you>.pycon.foo/hono

$ curl -sS  https://fast.<you>.pycon.foo      # must be refused
```

That last command is the one that matters. It should fail the TLS handshake —
the service's custom domain demands a client certificate from our trust store
and `curl` has none, while the identical request through the gateway succeeds
because API Gateway presents one. If the direct call *succeeds*, the service
side has not picked up `TRUSTSTORE`.

## 7.5 Tear down

```
$ npx cdk destroy
```

The trust store bucket empties itself and the log groups go with the stack —
both settings chosen for exactly this moment. The two *service* stacks were
deployed by the pipelines, not by this stack, so destroy them from their own
repositories.

---

← [06 — The app services](06-app-services.md)  ·  [08 — Design notes](08-design-notes.md) →
