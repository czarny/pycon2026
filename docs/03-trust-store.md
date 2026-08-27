# 03 — The `TrustStore` construct

← [02 — The CdkPipeline construct](02-cdk-pipeline.md)  ·  [04 — The PyconZone construct](04-delegated-zone.md) →

**Goal:** an API Gateway client certificate, published to S3 as a PEM bundle
that backend services point their mTLS trust store at — and that rotates itself
every six months.

**File:** [pycon2026/trust_store.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/trust_store.py)

## The problem

Our gateway proxies to backends that are themselves public HTTPS endpoints, and
we want them reachable *only* through the gateway. API Gateway can present a
**client certificate** on every integration request, and a backend's custom
domain can be given a **trust store** — a PEM bundle on S3 — so it accepts only
clients presenting a certificate from that bundle.

So we need the certificate's PEM in an S3 object. The catch: API Gateway
generates the certificate and does **not** expose its PEM as a CloudFormation
attribute. Only the `GetClientCertificate` API returns it.

That is what a **custom resource** is for — a slice of CloudFormation lifecycle
you implement in a Lambda.

## 3.1 Rotation encoded in the logical id

```python
now = datetime.datetime.now(datetime.timezone.utc)
rotation_suffix = f"{now.year}H{1 if now.month <= 6 else 2}"

client_certificate = apigateway.CfnClientCertificate(
    self,
    f"ClientCertificate{rotation_suffix}",
    description=f"{self.node.path} client certificate {rotation_suffix}",
)
self.client_certificate_id = client_certificate.ref
```

This is the cleverest line in the repository. A CloudFormation **logical id** is
a resource's identity: change it and CloudFormation creates the replacement and
deletes the original. The id here is `ClientCertificate2026H2`. Deploy in July
and it becomes `…2027H1` — a fresh certificate is issued, the bundle rewritten,
downstream pipelines re-run, the old certificate deleted. Rotation with no
rotation machinery, just an id that is a function of the calendar.

The cost is that **synth is no longer a pure function of the source**: two runs
either side of 1 July produce different templates. Deliberate, and confined to
one line — do not scatter `datetime.now()` through your constructs.

`CfnClientCertificate` is an **L1** construct, a direct mapping of the
CloudFormation resource. Use L1s without embarrassment when no L2 exists.

## 3.2 The bucket

```python
bucket = s3.Bucket(
    self,
    "Bucket",
    removal_policy=RemovalPolicy.DESTROY,
    auto_delete_objects=True,
    versioned=True,
    block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
)
```

`versioned=True` is load-bearing, not hygiene: the version id is how consumers
detect that the bundle changed (3.4). The removal settings keep workshop
accounts clean — S3 refuses to delete a non-empty bucket, so `auto_delete_objects`
adds a custom resource that empties it first.

## 3.3 The handler

`BUILDER_CODE` in the file is the whole Lambda. Its contract, under the CDK
Provider framework:

* `event["RequestType"]` is `Create`, `Update` or `Delete`. **Handle all three.**
  Forgetting `Delete` is the classic way to wedge a stack in
  `DELETE_IN_PROGRESS`.
* Return a `PhysicalResourceId`. If it changes between updates, CloudFormation
  treats that as a replacement and sends a `Delete` for the old one.
* Anything under `Data` becomes readable with `Fn::GetAtt` — that is how
  `VersionId` escapes the Lambda.
* You return a **plain dict**. The Provider framework signs and posts the real
  CloudFormation response for you, including on unhandled exceptions.

Two constraints shaped the code: `boto3` ships in the Lambda Python runtime, so
there is nothing to bundle, and inline CloudFormation code is capped at 4 KB.
Anything larger moves to `lambda_.Code.from_asset`.

## 3.4 Wiring it up

```python
builder.add_to_role_policy(
    iam.PolicyStatement(effect=iam.Effect.ALLOW, actions=["apigateway:GET"], resources=["*"])
)
bucket.grant_write(builder)

provider = cr.Provider(self, "BuilderProvider", on_event_handler=builder)

resource = CustomResource(
    self,
    "Bundle",
    service_token=provider.service_token,
    properties={
        "ClientCertificateId": self.client_certificate_id,
        "Bucket": bucket.bucket_name,
        "Key": TRUST_STORE_KEY,
    },
)
resource.node.add_dependency(bucket)
```

* `bucket.grant_write(builder)` is the **grant pattern** — the most useful habit
  in CDK. It writes the exact policy statements on both sides, adds any KMS
  grants, and creates the dependency edge. Reach for `grant_*` before you
  hand-write a policy. The `apigateway:GET` statement is the exception that
  proves the rule: there is no L2 grant for reading a client certificate.
* The explicit `add_dependency` is needed because the bucket name reaches the
  Lambda through a *property string*, not a grant, and CDK cannot infer ordering
  from a string.
* Passing `ClientCertificateId` as a property is what makes rotation propagate:
  a new id changes the property, CloudFormation sends an `Update`, the handler
  rewrites the object.

## 3.5 The output

```python
version = resource.get_att_string("VersionId")
self.uri = f"s3://{bucket.bucket_name}/{TRUST_STORE_KEY}?versionId={version}"
```

Consumers need bucket, key **and** version. The `s3://` scheme has no version
component, so this borrows the REST API's `versionId` query parameter; the other
side recovers all three with `urlparse` + `parse_qs`.

Both interpolated values are **tokens** — the f-string works because a token's
`str()` is a marker CDK substitutes at deploy time. This is exactly the value
that reaches step 02.4's tagging code as "unresolved".

The version is what makes rotation visible downstream: a rewritten bundle gets a
new version id → a new `TRUSTSTORE` value → a new pipeline tag → the service
redeploys.

## 3.6 Verify

Instantiate it temporarily in the stack (`TrustStore(self, "TrustStore")`), then:

```
$ npx cdk synth
$ uv run python -c "
import json
t = json.load(open('cdk.out/Pycon2026Stack.template.json'))
print(sorted({r['Type'] for r in t['Resources'].values()}))"
```

Note how much a two-line `cr.Provider` expands into — a framework Lambda, its
role, its log group. There are three `AWS::Lambda::Function`s here for one
handler you wrote.

---

← [02 — The CdkPipeline construct](02-cdk-pipeline.md)  ·  [04 — The PyconZone construct](04-delegated-zone.md) →
