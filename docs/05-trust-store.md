# 05 — The `TrustStore` construct

← [04 — The CdkPipeline construct](04-cdk-pipeline.md)  ·  [06 — The FastApp service](06-fast-app.md) →

**Goal:** an API Gateway client certificate, published to S3 as a PEM bundle
that backend services point their mTLS trust store at — and that rotates itself
every six months.

**New file:** [pycon2026/trust_store.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/trust_store.py)

## The problem

Our gateway proxies to backends that are themselves public HTTPS endpoints, and
we want them reachable *only* through the gateway. API Gateway can present a
**client certificate** on every integration request — that is the
`client_certificate_id` you already wired into the stage in 2.2 — and a
backend's custom domain can be given a **trust store**, a PEM bundle on S3, so
it accepts only clients presenting a certificate from that bundle.

So we need the certificate's PEM in an S3 object. The catch: API Gateway
generates the certificate and does **not** expose its PEM as a CloudFormation
attribute. Only the `GetClientCertificate` API returns it.

That is what a **custom resource** is for — a slice of CloudFormation lifecycle
you implement in a Lambda. Step 03's delegation record was one of these; this
time you write the handler.

## 5.1 The construct, in full

```python
# pycon2026/trust_store.py
"""A trust store bundle of API Gateway client certificate PEMs, held on S3.

The client certificate is rotated every half year: the logical id carries a
`<year>H<half>` suffix, so a new certificate is created (and the old one
replaced) whenever the half changes.
"""

import datetime

from aws_cdk import (
    CustomResource,
    Duration,
    RemovalPolicy,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
    custom_resources as cr,
)
from constructs import Construct

TRUST_STORE_KEY = "truststore.pem"

# Runs under the CDK custom-resource Provider framework, so it returns a plain
# dict rather than a signed CloudFormation response. boto3 ships in the Lambda
# Python runtime, so this needs no bundling and fits CloudFormation's 4 KB
# inline-code limit.
BUILDER_CODE = """
import boto3

apigateway = boto3.client("apigateway")
s3 = boto3.client("s3")


def handler(event, context):
    props = event["ResourceProperties"]
    bucket, key = props["Bucket"], props["Key"]
    physical_id = "s3://" + bucket + "/" + key

    if event["RequestType"] == "Delete":
        # The bucket itself is removed with the stack; nothing to undo here.
        return {"PhysicalResourceId": physical_id}

    pem = apigateway.get_client_certificate(
        clientCertificateId=props["ClientCertificateId"]
    )["pemEncodedCertificate"]

    response = s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=(pem.strip() + "\\n").encode(),
        ContentType="application/x-pem-file",
    )

    return {
        "PhysicalResourceId": physical_id,
        "Data": {"VersionId": response["VersionId"]},
    }
"""


class TrustStore(Construct):
    #: The certificate API Gateway presents to backends, verified against the bundle.
    client_certificate: apigateway.CfnClientCertificate
    #: Bucket, key and object version as one string:
    #: s3://<bucket>/<key>?versionId=<version>. The s3:// scheme has no version
    #: component of its own, so this borrows the S3 REST API's `versionId` query
    #: parameter: consumers recover all three parts with urlparse + parse_qs.
    uri: str

    def __init__(self, scope: Construct, id: str) -> None:
        super().__init__(scope, id)

        now = datetime.datetime.now(datetime.timezone.utc)
        rotation_suffix = f"{now.year}H{1 if now.month <= 6 else 2}"

        self.client_certificate = apigateway.CfnClientCertificate(
            self,
            f"ClientCertificate{rotation_suffix}",
            description=f"{self.node.path} client certificate {rotation_suffix}",
        )

        bucket = s3.Bucket(
            self,
            "Bucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        builder = lambda_.Function(
            self,
            "BuilderFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_inline(BUILDER_CODE),
            timeout=Duration.minutes(2),
            description=(
                "Fetches the API Gateway client certificate PEM and writes it " "to S3 as a trust store bundle"
            ),
        )
        builder.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["apigateway:GET"],
                resources=["*"],
            )
        )
        bucket.grant_write(builder)

        provider = cr.Provider(
            self,
            "BuilderProvider",
            on_event_handler=builder,
        )

        resource = CustomResource(
            self,
            "Bundle",
            service_token=provider.service_token,
            properties={
                "ClientCertificateId": self.client_certificate.ref,
                "Bucket": bucket.bucket_name,
                "Key": TRUST_STORE_KEY,
            },
        )
        resource.node.add_dependency(bucket)

        version = resource.get_att_string("VersionId")
        self.uri = f"s3://{bucket.bucket_name}/{TRUST_STORE_KEY}?versionId={version}"
```

## 5.2 Rotation encoded in the logical id

```python
now = datetime.datetime.now(datetime.timezone.utc)
rotation_suffix = f"{now.year}H{1 if now.month <= 6 else 2}"
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

## 5.3 The bucket

`versioned=True` is load-bearing, not hygiene: the version id is how consumers
detect that the bundle changed (5.6). The removal settings keep workshop
accounts clean — S3 refuses to delete a non-empty bucket, so
`auto_delete_objects` adds a custom resource that empties it first.

## 5.4 The handler

`BUILDER_CODE` is the whole Lambda. Its contract, under the CDK Provider
framework:

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

## 5.5 Wiring it up

* `bucket.grant_write(builder)` is the **grant pattern** — the most useful habit
  in CDK. It writes the exact policy statements on both sides, adds any KMS
  grants, and creates the dependency edge. Reach for `grant_*` before you
  hand-write a policy. The `apigateway:GET` statement is the exception that
  proves the rule: there is no L2 grant for reading a client certificate.
* The explicit `resource.node.add_dependency(bucket)` is needed because the
  bucket name reaches the Lambda through a *property string*, not a grant, and
  CDK cannot infer ordering from a string.
* Passing `ClientCertificateId` as a property is what makes rotation propagate:
  a new id changes the property, CloudFormation sends an `Update`, the handler
  rewrites the object.

## 5.6 The output

```python
version = resource.get_att_string("VersionId")
self.uri = f"s3://{bucket.bucket_name}/{TRUST_STORE_KEY}?versionId={version}"
```

Consumers need bucket, key **and** version. The `s3://` scheme has no version
component, so this borrows the REST API's `versionId` query parameter; the other
side recovers all three with `urlparse` + `parse_qs`.

Both interpolated values are **tokens** — the f-string works because a token's
`str()` is a marker CDK substitutes at deploy time. This is exactly the value
that reaches step 04.5's tagging code as "unresolved".

The version is what makes rotation visible downstream: a rewritten bundle gets a
new version id → a new `TRUSTSTORE` value → a new pipeline tag → the service
redeploys.

## 5.7 Give it to the gateway

`TrustStore` is created in the **stack**, not inside `Gateway`. It is not part
of the API — it is a *peer* the API and every backend share, so it belongs at
the nearest scope common to all of them.

What the API gets is one member of it: `trust_store.client_certificate`, the
`CfnClientCertificate` you declared as a public attribute in 5.1. That is the
only thing `Gateway` needs, and taking exactly that is why `gateway.py` imports
nothing from `trust_store.py` — the two constructs meet in the stack, not in
each other's import lists.

```python
# pycon2026/stack.py
import aws_cdk as cdk
from constructs import Construct

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
```

That switches on the second dormant branch from 2.2: the stage now presents
this certificate on every integration request, and any backend holding the
bundle can verify that the request came through our gateway.

## 5.8 Verify

```
$ npx cdk synth
```

Note how much a two-line `cr.Provider` expands into — a framework Lambda, its
role, its log group. There are three `AWS::Lambda::Function`s in the template
for one handler you wrote, and the third belongs to the bucket's auto-delete.

---

← [04 — The CdkPipeline construct](04-cdk-pipeline.md)  ·  [06 — The FastApp service](06-fast-app.md) →
