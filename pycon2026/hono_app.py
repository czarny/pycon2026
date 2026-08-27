"""The hono_app service, deployed by its own pipeline.

https://github.com/czarny/hono_app carries the application and the CDK app that
deploys it (a Hono handler on Lambda behind an HTTP API). This construct owns
neither: it stands up a pipeline that checks the repo out and runs that CDK app,
handing it the three values only this side knows —

  DOMAIN      the domain the service answers on: its subdomain of the
              delegated zone passed in
  TRUSTSTORE  the S3 URI of the trust store bundle whose client certificates its
              custom domain accepts, so only our API Gateway can reach it
              (taken from the TrustStore construct passed in)
  LABEL       free-form string the service echoes back as the "label" key of its
              JSON response, naming the deployment that owns it. Required, and
              deliberately not defaulted: nothing here knows what a deployment
              should call itself, and a wrong label is worse than an absent one
              because it is only ever read by someone asking which deployment
              answered.

All three arrive as CodeBuild environment variables, and a change to any of them
re-runs the pipeline (see CdkPipeline), so a rotated trust store is picked up on
deploy.

How the repo is built is likewise its own business: the pipeline runs the
buildspec.yml at its root.
"""

from aws_cdk import aws_route53 as route53
from constructs import Construct

from pycon2026.cdk_pipeline import CdkPipeline, SourceCode
from pycon2026.trust_store import TrustStore

#: The repo holding the application and its CDK app.
REPO_OWNER = "czarny"
REPO_NAME = "hono_app"
#: The subdomain of the delegated zone the service answers on.
SUBDOMAIN = "hono"


class HonoApp(Construct):
    #: The domain the service answers on, in the zone passed in.
    domain: str
    #: Base URL of the deployed service, for mounting behind our API.
    url: str
    #: What the service echoes back as the "label" key of its JSON response.
    label: str
    pipeline: CdkPipeline

    def __init__(
        self,
        scope: Construct,
        id: str,
        zone: route53.IHostedZone,
        trust_store: TrustStore,
        label: str,
        revision_selector: str = "main",
    ) -> None:
        super().__init__(scope, id)

        self.domain = f"{SUBDOMAIN}.{zone.zone_name}"
        self.url = f"https://{self.domain}"
        self.label = label

        self.pipeline = CdkPipeline(
            self,
            "Pipeline",
            source_code=SourceCode(
                owner=REPO_OWNER,
                repo=REPO_NAME,
                revision_selector=revision_selector,
            ),
            environment_variables={
                "DOMAIN": self.domain,
                "TRUSTSTORE": trust_store.uri,
                "LABEL": self.label,
            },
        )
