# Workshop: a multi-service AWS platform with CDK in Python

This repository is the finished outcome of the workshop. These documents walk
through building it, one construct at a time. Work through them in order.

## What you build

One CDK stack: a public API, its DNS, its client-certificate trust store, and
the delivery pipelines for two independently developed services.

```
                       pycon.foo                (parent zone, another account)
                           │  NS delegation, written cross-account at deploy time
                           ▼
                  <you>.pycon.foo               PyconZone   (Route 53)
                           │
             ┌─────────────┴─────────────────────────────┐
             │                                           │
    A record → API Gateway REST API              fast.<you>.pycon.foo
             (Gateway)                           hono.<you>.pycon.foo
                 │                                       ▲
                 │ /example  → https://example.com       │
                 │ /fast     → https://fast.<you>… ──────┤ mTLS: the backend
                 │ /hono     → https://hono.<you>… ──────┘ only accepts client
                 │                                         certs in our bundle
                 ▼
       client certificate ← TrustStore (S3: truststore.pem, versioned)
                                   │  s3://…/truststore.pem?versionId=…
                                   ▼
                        CdkPipeline (one per service)
                        GitHub → CodeBuild `cdk deploy`
                        env: DOMAIN, TRUSTSTORE
```

The two services (`fast_app`, `hono_app`) live in their own repositories with
their own CDK apps. This stack does not deploy them — it deploys *the pipelines
that deploy them*, handing each pipeline the two values only this side knows:
the domain the service answers on, and the trust store bundle it must accept
client certificates from.

## Steps

| # | Step | What you learn |
|---|------|----------------|
| [00](00-prerequisites.md) | Prerequisites | Tools, bootstrap, the GitHub connection |
| [01](01-init-project.md) | Initialise the project | `cdk init`, uv, black |
| [02](02-cdk-pipeline.md) | `CdkPipeline` | CodePipeline V2, branch vs tag triggers, forcing re-runs |
| [03](03-trust-store.md) | `TrustStore` | Custom resources, rotation via logical id, versioned S3 |
| [04](04-delegated-zone.md) | `PyconZone` | Subclassing an L2, cross-account zone delegation |
| [05](05-gateway.md) | `Gateway` | REST API, custom domain, HTTP proxy integrations |
| [06](06-app-services.md) | `FastApp`, `HonoApp` | Composing constructs, contracts between repos |
| [07](07-assemble-and-deploy.md) | Assemble and deploy | Wiring, synth, deploy, verify |
| [08](08-design-notes.md) | Design notes | Why the constructs look the way they do |

## Ground rules

* **Everything is a construct.** A class taking `(scope, id, …)` that creates
  resources under itself. Files in [pycon2026/](https://github.com/czarny/pycon2026/tree/main/pycon2026/) are one each.
* **Constructs take constructs, not strings.** `Gateway` takes a `TrustStore`,
  not a certificate id.
* **The stack is the wiring diagram.** [pycon2026/stack.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/stack.py)
  is 30 lines and tells you the whole architecture.
* **Synth after every step.** You need no AWS credentials until step 07.
