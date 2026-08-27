# Workshop: a multi-service AWS platform with CDK in Python

A hands-on workshop in building real infrastructure with the AWS CDK. Over nine
steps you write five constructs and wire them into a single stack, one construct
at a time. Work through them in order — each step builds on the last, and each
ends with a command that proves what you just wrote.

You need no CDK experience. You do need an AWS account for the final step; the
first seven need nothing but Python and Node.

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

The two services (`fast_app`, `hono_app`) are somebody else's code: each lives
in its own repository with its own CDK app. Your stack does not deploy them — it
deploys *the pipelines that deploy them*, handing each pipeline the two values
only your side knows: the domain the service answers on, and the trust store
bundle it must accept client certificates from.

That split is the point of the workshop. Most CDK tutorials build one app in one
repository; this one builds the platform that several teams deploy into.

## Steps

| # | Step | What you learn |
|---|------|----------------|
| [00](00-prerequisites.md) | Prerequisites | Tools, bootstrap, the GitHub connection |
| [01](01-init-project.md) | Initialise the project | `cdk init`, uv, project layout |
| [02](02-cdk-pipeline.md) | `CdkPipeline` | CodePipeline V2, branch vs tag triggers, forcing re-runs |
| [03](03-trust-store.md) | `TrustStore` | Custom resources, rotation via logical id, versioned S3 |
| [04](04-delegated-zone.md) | `PyconZone` | Subclassing an L2, cross-account zone delegation |
| [05](05-gateway.md) | `Gateway` | REST API, custom domain, HTTP proxy integrations |
| [06](06-app-services.md) | `FastApp`, `HonoApp` | Composing constructs, contracts between repos |
| [07](07-assemble-and-deploy.md) | Assemble and deploy | Wiring, synth, deploy, verify |
| [08](08-design-notes.md) | Design notes | Why the constructs look the way they do |

## Ground rules

Four ideas run through every step. They are worth reading now and again at the
end, when [08 — Design notes](08-design-notes.md) argues for them properly.

* **Everything is a construct.** A class taking `(scope, id, …)` that creates
  resources under itself. You write one per file, and one per step.
* **Constructs take constructs, not strings.** `Gateway` takes a `TrustStore`,
  not a certificate id.
* **The stack is the wiring diagram.** By step 07 it is thirty lines that
  declare no resources at all — five constructs and the edges between them.
* **Synth after every step.** `cdk synth` is the feedback loop, and it needs no
  AWS credentials.
