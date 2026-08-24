from aws_cdk import Stack
from constructs import Construct

from pycon2026.api import Api
from pycon2026.delegated_hosted_zone import DelegatedHostedZone, ParentZone
from pycon2026.fast_app import FastApp


class Pycon2026Stack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        zone = DelegatedHostedZone(
            self,
            "DelegatedZone",
            record_name="czarny",
            parent=ParentZone(zone_name="pycon.foo"),
        )

        api = Api(self, "Api", zone)
        api.add_http_proxy("example", "https://example.com")

        # Deployed by its own pipeline, on its own subdomain of the delegated
        # zone, and reachable only through this API — its custom domain accepts
        # just the client certificates in our trust store.
        fast_app = FastApp(
            self,
            "FastApp",
            domain=f"fast.{zone.zone_name}",
            truststore=api.trust_store.uri,
        )
        api.add_http_proxy("fast", fast_app.url)
