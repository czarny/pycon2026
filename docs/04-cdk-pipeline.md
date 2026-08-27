# 04 — The `CdkPipeline` construct

← [03 — The PyconZone construct](03-delegated-zone.md)  ·  [05 — The TrustStore construct](05-trust-store.md) →

**Goal:** a reusable construct that stands up a CodePipeline which checks out a
GitHub repository and deploys it with a single `cdk deploy` CodeBuild stage.

**New file:** [pycon2026/cdk_pipeline.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/cdk_pipeline.py)

This is the one step where the stack does not grow: nothing instantiates
`CdkPipeline` yet, so your template is unchanged at the end of it. Write it
whole anyway. It is the construct that carries everything structural about
deploying a repository, so that anything using it needs only a repo name and a
handful of values.

## Why not `aws_cdk.pipelines`?

That module builds self-mutating pipelines for *the CDK app it lives in*. Here
the job is the opposite: deploy **other repositories'** CDK apps, whose build
steps we do not own. So we drop a level, to `aws_codepipeline`.

## 4.1 The construct, in full

```python
# pycon2026/cdk_pipeline.py
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
```

## 4.2 The contract

Two habits worth stealing: a **frozen dataclass** for a group of related
parameters (`SourceCode`, `PipelineOutputs`), and **public attributes declared
at class level** — `pipeline` and `outputs` are the construct's API, everything
else is internal.

## 4.3 Branch or tag, decided by the selector

```python
is_tag = bool(TAG_VERSION_PATTERN.match(source_code.revision_selector))
```

`"main"` deploys on every push to that branch; `"v1.4.2"` deploys when that tag
is pushed. There is no mode flag, so no combination of flags can contradict
itself.

In tag mode the source action's own push trigger is disabled
(`trigger_on_push=not is_tag`) and a `GitPushFilter` on the pipeline takes over,
with `tags_excludes` stopping `v1.2.3-rc1` from firing a `v1.2.3` pipeline.
`PipelineType.V2` is required for those filters; `cross_account_keys=False`
skips a customer-managed KMS key the pipeline does not need.

The source action reads the connection ARN from SSM when the caller does not
supply one:

```python
connection_arn=source_code.connection_arn
or ssm.StringParameter.value_for_string_parameter(self, CONNECTION_ARN_PARAMETER),
```

`value_for_string_parameter` does **not** read SSM at synth time. It adds a
CloudFormation parameter of type `AWS::SSM::Parameter::Value<String>`, resolved
at *deploy* time — which is what lets the connection be created once, out of
band (step 00), and referenced by name. (`value_from_lookup` does the opposite:
a real API call during synth, cached in `cdk.context.json`.)

## 4.4 The deploy stage

Three decisions in the `codebuild.PipelineProject`:

1. **The build role is tiny.** It carries no deploy permissions — only
   `sts:AssumeRole` on `arn:aws:iam::*:role/cdk-*` and reads of the
   `/cdk-bootstrap/*` parameters, which is exactly what `cdk deploy` does. All
   real authority stays in the bootstrap roles.
2. **`privileged=True`** gives the build a Docker daemon, which CDK asset
   bundling needs.
3. **`BuildSpec.from_source_filename("buildspec.yml")`** reads the build
   instructions from the checked-out repository. How `fast_app` builds itself is
   `fast_app`'s business; this construct only supplies inputs.

The explicit `LogGroup` with `RemovalPolicy.DESTROY` means tearing the stack
down actually removes the logs. CodeBuild's implicit log group is created
outside CloudFormation and survives forever.

## 4.5 Making a changed value re-run the pipeline

Change only a CodeBuild *environment variable* and CloudFormation updates the
build project — but the pipeline resource is untouched, so nothing re-runs and
the service keeps the old value. That matters: `TRUSTSTORE` changes when the
certificate rotates, and the whole point of rotating is that the services pick
it up.

```python
for name, value in (environment_variables or {}).items():
    Tags.of(self.pipeline).add(
        f"ENV.{name}",
        (Fn.base64(value) if Token.is_unresolved(value) else hashlib.sha256(value.encode()).hexdigest()),
    )
```

A changed value changes a tag, which updates the pipeline resource, which —
with `restart_execution_on_update=True` — re-runs it.

The value is not tagged verbatim because tag values are length-capped and
charset-limited (IAM rejects the `?` in an S3 URI carrying a `?versionId=`). So
resolved strings are hashed, and **tokens** — placeholders for values only known
at deploy time — get `Fn.base64`, whose output every tag accepts. Both change
exactly when the value does, which is all the tag is for.

`Token.is_unresolved` is the guard you need whenever synth-time Python has to
branch on a value that may not exist yet.

## 4.6 Verify

Nothing instantiates `CdkPipeline` yet, so the template must be **unchanged**:

```
$ uv run python -c "from pycon2026.cdk_pipeline import CdkPipeline; print('ok')"
$ npx cdk synth
$ npx cdk diff        # if you deployed in step 03: "There were no differences"
```

---

← [03 — The PyconZone construct](03-delegated-zone.md)  ·  [05 — The TrustStore construct](05-trust-store.md) →
