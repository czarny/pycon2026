"""A subdomain hosted zone, delegated from a parent zone in another account.

The parent account holds a role this account may assume to write the NS record
that delegates the subdomain, so the delegation happens as part of the deploy.
"""

from dataclasses import dataclass

from aws_cdk import (
    Stack,
    aws_iam as iam,
    aws_route53 as route53,
)
from constructs import Construct

#: Account that owns the parent zone and the delegation role.
PARENT_ACCOUNT_ID = "097446187891"
#: Role in the parent account, assumed to write the NS record.
DELEGATION_ROLE_NAME = "CrossAccountZoneDelegationRole"


@dataclass(frozen=True)
class ParentZone:
    """The zone being delegated from, in the account that owns it."""

    zone_name: str
    account_id: str = PARENT_ACCOUNT_ID
    #: Role in the parent account this account assumes to write the NS record.
    delegation_role_name: str = DELEGATION_ROLE_NAME


class DelegatedHostedZone(route53.HostedZone):

    def __init__(
        self, scope: Construct, id: str, record_name: str, parent: ParentZone
    ) -> None:
        super().__init__(scope, id, zone_name=f"{record_name}.{parent.zone_name}")

        delegation_role_arn = Stack.of(self).format_arn(
            region="",  # IAM is global in each partition
            service="iam",
            account=parent.account_id,
            resource="role",
            resource_name=parent.delegation_role_name,
        )
        route53.CrossAccountZoneDelegationRecord(
            self,
            "DelegateNsRecord",
            parent_hosted_zone_name=parent.zone_name,
            delegated_zone=self,
            delegation_role=iam.Role.from_role_arn(
                self, "DelegationRole", delegation_role_arn
            ),
        )
