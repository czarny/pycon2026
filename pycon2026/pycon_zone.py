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
