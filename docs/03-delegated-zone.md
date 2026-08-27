# 03 — The `PyconZone` construct, and the gateway's domain

← [02 — The Gateway construct](02-gateway.md)  ·  [04 — The CdkPipeline construct](04-cdk-pipeline.md) →

**Goal:** own `<you>.pycon.foo` in AWS account, with the NS delegation written
into the parent zone — in a different account — as part of the deploy, and step
02's API served from it under an ACM certificate.

**New file:** [pycon2026/pycon_zone.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/pycon_zone.py)

## The problem

Creating a hosted zone for `<you>.pycon.foo` in your account is trivial and
useless on its own: nothing resolves it until the *parent* zone contains an NS
record pointing at your zone's name servers. And you have no access to the
parent account.

Route 53's answer is a role in the parent account that your account may assume
for exactly that one write. CDK wraps it as
`route53.CrossAccountZoneDelegationRecord`.

## 3.1 The construct, in full

```python
# pycon2026/pycon_zone.py
"""This account's subdomain of the conference zone, delegated from pycon.foo.

The account that owns pycon.foo holds a role this account may assume to write
the NS record that delegates the subdomain, so the delegation happens as part
of the deploy.
"""

from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_route53 as route53,
)
from constructs import Construct

#: The zone delegated from. Fixed: this construct delegates from no other.
PARENT_ZONE_NAME = "pycon.foo"
#: Account that owns the parent zone and the delegation role.
PARENT_ACCOUNT_ID = "097446187891"
#: Role in the parent account, assumed to write the NS record.
DELEGATION_ROLE_NAME = "CrossAccountZoneDelegationRole"


class PyconZone(route53.HostedZone):
    """A subdomain of pycon.foo, delegated to this account."""

    def __init__(self, scope: Construct, id: str, record_name: str) -> None:
        super().__init__(scope, id, zone_name=f"{record_name}.{PARENT_ZONE_NAME}")

        delegation_role_arn = Stack.of(self).format_arn(
            region="",  # IAM is global in each partition
            service="iam",
            account=PARENT_ACCOUNT_ID,
            resource="role",
            resource_name=DELEGATION_ROLE_NAME,
        )
        route53.CrossAccountZoneDelegationRecord(
            self,
            "DelegateNsRecord",
            parent_hosted_zone_name=PARENT_ZONE_NAME,
            delegated_zone=self,
            delegation_role=iam.Role.from_role_arn(self, "DelegationRole", delegation_role_arn),
        )
```

## 3.2 Subclass the L2

`PyconZone` **is** a `HostedZone` rather than *having* one, which is right here:
everything downstream — `acm.CertificateValidation.from_dns(zone)`,
`route53.ARecord(zone=…)`, `zone.zone_name` — wants an `IHostedZone`, and
subclassing satisfies that interface with no `.hosted_zone` unwrapping at every
call site.

Subclass when your construct genuinely *is* the thing plus some setup. Prefer
composition when it is a collection of things, as in `Gateway`.

## 3.3 Delegate

* **`Stack.of(self)`** walks up the construct tree to the enclosing stack — how
  any construct reaches region, account, partition and `format_arn` without
  being handed them.
* **`format_arn`** rather than an f-string, because it picks up the right
  partition (`aws`, `aws-cn`, `aws-us-gov`) automatically.
* **`Role.from_role_arn`** *imports* a role that already exists elsewhere; it
  creates nothing. Every L2 has these `from_*` methods, and they are how you
  reference resources you do not own.
* `delegated_zone=self` works because we subclassed.

Under the hood this is a **custom resource** — a Lambda that assumes the role and
calls `ChangeResourceRecordSets` on the parent zone, because CloudFormation has
no native resource for writing into another account's zone. Note in the synthesized
template how much a two-line L2 expands into: a Lambda, a role and a log group.

## 3.4 Give the zone to the gateway

Nothing changes in `gateway.py`. The zone branch you already wrote wakes up as
soon as a zone is passed:

```python
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
```

* **`CertificateValidation.from_dns(zone)`** hands ACM the zone, so CDK writes
  the validation record for you and renewals validate themselves forever. Give
  ACM a zone whenever you have one.
* **An alias record, not a CNAME.** Only an alias can sit at a zone apex, and
  this record is at the apex (`domain_name=zone.zone_name`).
* **`endpoint_type=REGIONAL`** here has to agree with the API's endpoint type
  from 2.2, and is why the certificate can live in this stack's region.

This is what "constructs take constructs" buys: `Gateway` receives an
`IHostedZone`, and from it derives a domain name, a certificate, a validation
record and an alias target. Had it taken `domain_name: str`, ACM would have had
nowhere to write.

## 3.5 The stack so far

```python
# pycon2026/stack.py
import aws_cdk as cdk
from constructs import Construct

from pycon2026.gateway import Gateway
from pycon2026.pycon_zone import PyconZone


class Stack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        zone = PyconZone(self, "DelegatedZone", record_name="czarny")

        gateway = Gateway(self, "Gateway", zone)
        gateway.add_http_proxy("example", "https://example.com")
```

Replace `czarny` with your own name. **This is the only place your identity
appears** — everything else derives from `zone.zone_name`.

## 3.6 Verify

```
$ npx cdk synth
```

## 3.7 Worth deploying now

Everything here synthesizes fine without credentials, but this step adds the
workshop's slowest resource: the ACM certificate blocks until DNS validation
succeeds, which needs the delegation above to have propagated. Several minutes is
normal, so it is worth starting that wait now rather than at the end:

```
$ npx cdk deploy
$ dig +short NS <you>.pycon.foo @8.8.8.8
$ curl -sSI https://<you>.pycon.foo/example
```

---

← [02 — The Gateway construct](02-gateway.md)  ·  [04 — The CdkPipeline construct](04-cdk-pipeline.md) →
