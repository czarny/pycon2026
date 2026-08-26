"""A CDK deployment pipeline construct.

A CodePipeline that pulls source from GitHub via a CodeStar connection and
deploys it with a single CodeBuild `cdk deploy` stage. Supports either a branch
trigger (push to branch) or a tag trigger (push of a matching tag).
"""

import hashlib
import re
from dataclasses import dataclass
from collections.abc import Mapping

from aws_cdk import (
    Fn,
    RemovalPolicy,
    Tags,
    Token,
    aws_codebuild as codebuild,
    aws_codepipeline as codepipeline,
    aws_codepipeline_actions as actions,
    aws_iam as iam,
    aws_logs as logs,
    aws_ssm as ssm,
)
from constructs import Construct

# Matches semver-ish tag selectors, e.g. "v1.2.3". Anything else is a branch name.
TAG_VERSION_PATTERN = re.compile(r"^v?\d+\.\d+\.\d+$")

#: SSM parameter holding the CodeConnections ARN, used when SourceCode omits one.
#: Create it once, out of band:
#:   aws ssm put-parameter --name /pycon2026/connection-arn --type String \
#:       --value arn:aws:codeconnections:...:connection/<uuid>
CONNECTION_ARN_PARAMETER = "/codestar-connection/github-czarny"

#: Build instructions come from the source repo, not from here: CodeBuild reads
#: this file from the root of the checked-out source artifact.
BUILDSPEC_FILENAME = "buildspec.yml"


@dataclass(frozen=True)
class SourceCode:
    """Where the pipeline pulls its source from."""

    owner: str
    repo: str
    #: Either a branch name or a tag (matched against TAG_VERSION_PATTERN).
    revision_selector: str
    #: ARN of the CodeConnections connection granting access to the repo.
    #: Defaults to the value of the CONNECTION_ARN_PARAMETER SSM parameter,
    #: which CloudFormation resolves at deploy time.
    connection_arn: str | None = None


@dataclass(frozen=True)
class PipelineOutputs:
    source: codepipeline.Artifact
    deploy: codepipeline.Artifact


class CdkPipeline(Construct):
    pipeline: codepipeline.Pipeline
    outputs: PipelineOutputs

    def __init__(
        self,
        scope: Construct,
        id: str,
        source_code: SourceCode,
        environment_variables: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(scope, id)

        is_tag = bool(TAG_VERSION_PATTERN.match(source_code.revision_selector))

        self.outputs = PipelineOutputs(
            source=codepipeline.Artifact(),
            deploy=codepipeline.Artifact(),
        )

        source_action = actions.CodeStarConnectionsSourceAction(
            action_name="Source",
            connection_arn=source_code.connection_arn
            or ssm.StringParameter.value_for_string_parameter(self, CONNECTION_ARN_PARAMETER),
            owner=source_code.owner,
            repo=source_code.repo,
            # For tag triggers, branch is not used for filtering — we use the trigger config.
            # CodeStarConnectionsSourceAction requires branch, so we default to 'main' for tag triggers.
            branch="main" if is_tag else source_code.revision_selector,
            output=self.outputs.source,
            # Disable default trigger for tag-based pipelines — trigger config handles it.
            trigger_on_push=not is_tag,
        )

        self.pipeline = codepipeline.Pipeline(
            self,
            "Pipeline",
            cross_account_keys=False,
            pipeline_type=codepipeline.PipelineType.V2,
            restart_execution_on_update=True,
            triggers=(
                [
                    codepipeline.TriggerProps(
                        provider_type=codepipeline.ProviderType.CODE_STAR_SOURCE_CONNECTION,
                        git_configuration=codepipeline.GitConfiguration(
                            source_action=source_action,
                            push_filter=[
                                codepipeline.GitPushFilter(
                                    tags_includes=[source_code.revision_selector],
                                    tags_excludes=[source_code.revision_selector + "-*"],
                                ),
                            ],
                        ),
                    ),
                ]
                if is_tag
                else []
            ),
        )

        self.pipeline.add_stage(stage_name="Source", actions=[source_action])

        build_log_group = logs.LogGroup(
            self,
            "BuildLogGroup",
            removal_policy=RemovalPolicy.DESTROY,
        )

        build_project = codebuild.PipelineProject(
            self,
            "Project",
            logging=codebuild.LoggingOptions(
                cloud_watch=codebuild.CloudWatchLoggingOptions(log_group=build_log_group),
            ),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.AMAZON_LINUX_2023_5,
                compute_type=codebuild.ComputeType.SMALL,
                privileged=True,
            ),
            role=iam.Role(
                self,
                "Role",
                assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
                inline_policies={
                    "cdkDeploy": iam.PolicyDocument(
                        statements=[
                            iam.PolicyStatement(
                                actions=["sts:AssumeRole"],
                                resources=["arn:aws:iam::*:role/cdk-*"],
                            ),
                            iam.PolicyStatement(
                                actions=["ssm:GetParameter"],
                                resources=["arn:aws:ssm:*:*:parameter/cdk-bootstrap/*"],
                            ),
                        ],
                    ),
                },
            ),
            environment_variables={
                name: codebuild.BuildEnvironmentVariable(value=value)
                for name, value in (environment_variables or {}).items()
            },
            build_spec=codebuild.BuildSpec.from_source_filename(BUILDSPEC_FILENAME),
        )

        self.pipeline.add_stage(
            stage_name="Deploy",
            actions=[
                actions.CodeBuildAction(
                    action_name="Deploy",
                    input=self.outputs.source,
                    project=build_project,
                    outputs=[self.outputs.deploy],
                ),
            ],
        )

        # Tag the pipeline with one tag per environment variable so that changing a
        # value counts as a resource update in CloudFormation which — combined with
        # restart_execution_on_update above — re-runs the pipeline. Neither form of
        # the value is tagged verbatim: tag values are constrained (IAM in particular
        # allows only [\p{L}\p{Z}\p{N}_.:/=+\-@], which rules out the `?` in an S3
        # URI carrying a versionId) and capped in length. Resolved values are hashed;
        # tokens are base64-encoded at deploy time by CloudFormation, whose alphabet
        # sits inside every tag charset. Both change when the value does, which is all
        # the tag is for.
        for name, value in (environment_variables or {}).items():
            Tags.of(self.pipeline).add(
                f"ENV.{name}",
                (Fn.base64(value) if Token.is_unresolved(value) else hashlib.sha256(value.encode()).hexdigest()),
            )
