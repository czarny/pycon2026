# Workshop: a multi-service AWS platform with CDK in Python

A hands-on workshop in building real infrastructure with the AWS CDK. Over nine
steps you write five constructs and wire them into a single stack, one construct
at a time. Work through them in order — each step builds on the last, and each
ends with a command that proves what you just wrote.

You need no CDK experience. You do need an AWS account: every step synthesizes
without credentials, but from step 02 the stack is deployable, and step 03 is
worth deploying because its certificate takes minutes to validate.

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
| [00](00-prerequisites.md) | Prerequisites | Tools, SSO, bootstrap, the GitHub connection |
| [01](01-init-project.md) | Initialise the project | `cdk init`, uv, project layout |
| [02](02-gateway.md) | `Gateway` | REST API, HTTP proxy integrations, `add_*` methods |
| [03](03-delegated-zone.md) | `PyconZone` + the API's domain | Subclassing an L2, cross-account delegation, ACM + alias records |
| [04](04-cdk-pipeline.md) | `CdkPipeline` | CodePipeline V2, branch vs tag triggers, forcing re-runs |
| [05](05-trust-store.md) | `TrustStore` | Custom resources, rotation via logical id, versioned S3 |
| [06](06-fast-app.md) | `FastApp` | Composing constructs, contracts between repos |
| [07](07-hono-app.md) | `HonoApp`, assemble and deploy | Wiring, synth, deploy, verify end to end |
| [08](08-design-notes.md) | Design notes | Why the constructs look the way they do |

## How a step works

Every step from 02 on has the same shape, and the shape is deliberate:

1. **One new construct file, written whole.** You type the finished construct,
   including the parts nothing calls yet. `Gateway` in step 02 already accepts a
   hosted zone and a client certificate that nothing produces until steps 03 and
   05; those branches sit dormant until you pass the argument. A construct that
   keeps working when a dependency is missing is one you can build and test in
   isolation — see [08 — Design notes](08-design-notes.md).
2. **The stack grows by a line or two.** Each step prints
   [stack.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/stack.py) as it stands at the
   end of it, so you can always diff against what you have. (Step 04 is the one
   exception: `CdkPipeline` has no caller until step 06, and the template is
   unchanged.)
3. **A verify command.** Usually `cdk synth` plus three lines of Python against
   the emitted template.

## Ground rules

Four ideas run through every step. They are worth reading now and again at the
end, when [08 — Design notes](08-design-notes.md) argues for them properly.

* **Everything is a construct.** A class taking `(scope, id, …)` that creates
  resources under itself. You write one per file, and one per step.
* **Constructs take constructs, not strings.** `Gateway` takes the client
  certificate, not its id; `FastApp` takes the `TrustStore`, not its URI.
* **The stack is the wiring diagram.** By step 07 it is thirty lines that
  declare no resources at all — five constructs and the edges between them.
* **Synth after every step.** `cdk synth` is the feedback loop, and it needs no
  AWS credentials.
