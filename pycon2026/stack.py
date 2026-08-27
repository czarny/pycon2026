import aws_cdk as cdk
from constructs import Construct

from pycon2026.fast_app import FastApp
from pycon2026.gateway import Gateway
from pycon2026.hono_app import HonoApp
from pycon2026.pycon_zone import PyconZone
from pycon2026.trust_store import TrustStore


class Stack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        zone = PyconZone(self, "DelegatedZone", record_name="czarny")

        trust_store = TrustStore(self, "TrustStore")

        gateway = Gateway(self, "Gateway", zone, client_certificate=trust_store.client_certificate)
        gateway.add_http_proxy("example", "https://example.com")

        # Each deployed by its own pipeline, on its own subdomain of the
        # delegated zone, and reachable only through this API — their custom
        # domains accept just the client certificates in our trust store.
        fast_app = FastApp(
            self,
            "FastApp",
            domain=f"fast.{zone.zone_name}",
            trust_store=trust_store,
        )
        gateway.add_http_proxy("fast", fast_app.url)

        hono_app = HonoApp(
            self,
            "HonoApp",
            domain=f"hono.{zone.zone_name}",
            trust_store=trust_store,
        )
        gateway.add_http_proxy("hono", hono_app.url)
