"""A REST API that authenticates itself to its HTTP backends with a client certificate.

Backends are mounted with `add_http_proxy`. Every request API Gateway forwards
to one carries the trust store's client certificate, so the backend can verify
the caller by checking it against the trust store bundle.

The API is served from the delegated zone's domain name, with a DNS-validated
certificate and an alias record pointing at it.
"""

from aws_cdk import (
    aws_apigateway as apigateway,
    aws_certificatemanager as acm,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
)
from constructs import Construct

from pycon2026.trust_store import TrustStore


class Api(Construct):
    rest_api: apigateway.RestApi
    trust_store: TrustStore

    def __init__(self, scope: Construct, id: str, zone: route53.IHostedZone) -> None:
        super().__init__(scope, id)

        self.trust_store = TrustStore(self, "TrustStore")

        self.rest_api = apigateway.RestApi(
            self,
            "RestApi",
            # Regional, so the certificate can live in this stack's region;
            # an edge-optimised API would require one in us-east-1.
            endpoint_types=[apigateway.EndpointType.REGIONAL],
            deploy_options=apigateway.StageOptions(
                # Presented to every backend on integration requests.
                client_certificate_id=self.trust_store.client_certificate_id,
            ),
        )

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
            target=route53.RecordTarget.from_alias(
                route53_targets.ApiGatewayDomain(domain)
            ),
        )

    def add_http_proxy(self, path: str, backend_url: str) -> apigateway.Resource:
        """Mount `backend_url` at `path`, proxying every method and sub-path to it."""
        resource = self.rest_api.root.resource_for_path(path)
        # `{proxy+}` below matches sub-paths only, so the mount point itself
        # needs its own method, integrated with the backend's root.
        resource.add_method(
            "ANY",
            apigateway.HttpIntegration(
                backend_url,
                http_method="ANY",
                proxy=True,
            ),
        )
        resource.add_proxy(
            any_method=True,
            default_integration=apigateway.HttpIntegration(
                f"{backend_url}/{{proxy}}",
                http_method="ANY",
                proxy=True,
                options=apigateway.IntegrationOptions(
                    request_parameters={
                        "integration.request.path.proxy": "method.request.path.proxy",
                    },
                ),
            ),
            default_method_options=apigateway.MethodOptions(
                request_parameters={"method.request.path.proxy": True},
            ),
        )
        return resource
