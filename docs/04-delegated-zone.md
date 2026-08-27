# 04 — The `PyconZone` construct

**Goal:** own `<you>.pycon.foo` in your account, with the NS delegation written
into the parent zone — in a different account — as part of the deploy.

**File:** [pycon2026/pycon_zone.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/pycon_zone.py)

## The problem

Creating a hosted zone for `czarny.pycon.foo` in your account is trivial and
useless on its own: nothing resolves it until the *parent* zone contains an NS
record pointing at your zone's name servers. And you have no access to the
parent account.

Route 53's answer is a role in the parent account that your account may assume
for exactly that one write. CDK wraps it as
`route53.CrossAccountZoneDelegationRecord`.

## 4.1 Subclass the L2

```python
PARENT_ZONE_NAME = "pycon.foo"
PARENT_ACCOUNT_ID = "097446187891"
DELEGATION_ROLE_NAME = "CrossAccountZoneDelegationRole"


class PyconZone(route53.HostedZone):
    """A subdomain of pycon.foo, delegated to this account."""

    def __init__(self, scope: Construct, id: str, record_name: str) -> None:
        super().__init__(scope, id, zone_name=f"{record_name}.{PARENT_ZONE_NAME}")
```

`PyconZone` **is** a `HostedZone` rather than *having* one, which is right here:
everything downstream — `acm.CertificateValidation.from_dns(zone)`,
`route53.ARecord(zone=…)` — wants an `IHostedZone`, and subclassing satisfies
that interface with no `.hosted_zone` unwrapping at every call site.

Subclass when your construct genuinely *is* the thing plus some setup. Prefer
composition when it is a collection of things, as in `Gateway` and `TrustStore`.

## 4.2 Delegate

```python
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

* **`Stack.of(self)`** walks up the construct tree to the enclosing stack — how
  any construct reaches region, account, partition and `format_arn` without
  being handed them.
* **`format_arn`** rather than an f-string, because it picks up the right
  partition (`aws`, `aws-cn`, `aws-us-gov`) automatically.
* **`Role.from_role_arn`** *imports* a role that already exists elsewhere; it
  creates nothing. Every L2 has these `from_*` methods, and they are how you
  reference resources you do not own.
* `delegated_zone=self` works because we subclassed.

Under the hood this is another custom resource — a Lambda that assumes the role
and calls `ChangeResourceRecordSets` on the parent. Having built one by hand in
step 03, you know exactly what it is doing.

## 4.3 Use it

In [pycon2026/stack.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/stack.py):

```python
zone = PyconZone(self, "DelegatedZone", record_name="czarny")
```

Replace `czarny` with your own name. This is the only place your identity
appears.

## 4.4 Verify

```
$ npx aws-cdk synth
$ uv run python -c "
import json
t = json.load(open('cdk.out/Pycon2026Stack.template.json'))
for lid, r in t['Resources'].items():
    if r['Type'].startswith(('AWS::Route53', 'Custom::CrossAccount')):
        print(r['Type'], lid)"
```

After the deploy in step 07, `dig +short NS <you>.pycon.foo @8.8.8.8` confirms
the delegation really took. Empty means either the deploy has not run or the
parent account's role does not trust yours.

→ [05 — The Gateway construct](05-gateway.md)
