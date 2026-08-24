"""The fast_app FastAPI service, deployed by its own pipeline.

https://github.com/czarny/fast_app carries the application and the CDK app that
deploys it (a Lambda behind an HTTP API). This construct owns neither: it stands
up a pipeline that checks the repo out and runs that CDK app, handing it the two
values only this side knows —

  DOMAIN      the domain the service answers on, in our delegated zone
  TRUSTSTORE  the S3 URI of the trust store bundle whose client certificates its
              custom domain accepts, so only our API Gateway can reach it

Both arrive as CodeBuild environment variables, and a change to either re-runs
the pipeline (see CdkPipeline), so a rotated trust store is picked up on deploy.

How the repo is built is likewise its own business: the pipeline runs the
buildspec.yml at its root.
"""

from constructs import Construct

from pycon2026.cdk_pipeline import CdkPipeline, SourceCode

#: The repo holding the application and its CDK app.
REPO_OWNER = "czarny"
REPO_NAME = "fast_app"


class FastApp(Construct):
    #: Base URL of the deployed service, for mounting behind our API.
    url: str
    pipeline: CdkPipeline

    def __init__(
        self,
        scope: Construct,
        id: str,
        domain: str,
        truststore: str,
        revision_selector: str = "main",
    ) -> None:
        super().__init__(scope, id)

        self.url = f"https://{domain}"

        self.pipeline = CdkPipeline(
            self,
            "Pipeline",
            source_code=SourceCode(
                owner=REPO_OWNER,
                repo=REPO_NAME,
                revision_selector=revision_selector,
            ),
            environment_variables={
                "DOMAIN": domain,
                "TRUSTSTORE": truststore,
            },
        )
