# 02 — The `CdkPipeline` construct

← [01 — Initialise the project](01-init-project.md)  ·  [03 — The TrustStore construct](03-trust-store.md) →

**Goal:** a reusable construct that stands up a CodePipeline which checks out a
GitHub repository and deploys it with a single `cdk deploy` CodeBuild stage.

**File:** [pycon2026/cdk_pipeline.py](https://github.com/czarny/pycon2026/blob/main/pycon2026/cdk_pipeline.py)

## Why not `aws_cdk.pipelines`?

That module builds self-mutating pipelines for *the CDK app it lives in*. Here
the job is the opposite: deploy **other repositories'** CDK apps, whose build
steps we do not own. So we drop a level, to `aws_codepipeline`.

## 2.1 The contract

```python
@dataclass(frozen=True)
class SourceCode:
    owner: str
    repo: str
    #: Either a branch name or a tag (matched against TAG_VERSION_PATTERN).
    revision_selector: str
    connection_arn: str | None = None

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
```

Two habits to adopt for every construct here: a **frozen dataclass** for a group
of related parameters, and **public attributes declared at class level** —
anything not declared is an implementation detail.

## 2.2 Branch or tag, decided by the selector

```python
TAG_VERSION_PATTERN = re.compile(r"^v?\d+\.\d+\.\d+$")

is_tag = bool(TAG_VERSION_PATTERN.match(source_code.revision_selector))
```

`"main"` deploys on every push to that branch; `"v1.4.2"` deploys when that tag
is pushed. There is no mode flag, so no combination of flags can contradict
itself.

The source action reads the connection ARN from SSM when the caller does not
supply one:

```python
connection_arn=source_code.connection_arn
or ssm.StringParameter.value_for_string_parameter(self, CONNECTION_ARN_PARAMETER),
```

`value_for_string_parameter` does **not** read SSM at synth time. It adds a
CloudFormation parameter of type `AWS::SSM::Parameter::Value<String>`, resolved
at *deploy* time — which is what lets the connection be created once, out of
band, and referenced by name. (`value_from_lookup` does the opposite: a real API
call during synth, cached in `cdk.context.json`.)

In tag mode the action's own push trigger is disabled (`trigger_on_push=not
is_tag`) and a `GitPushFilter` on the pipeline takes over, with `tags_excludes`
stopping `v1.2.3-rc1` from firing a `v1.2.3` pipeline. `PipelineType.V2` is
required for those filters; `cross_account_keys=False` skips a customer-managed
KMS key the pipeline does not need.

## 2.3 The deploy stage

Read the `codebuild.PipelineProject` in the file. Three decisions in it:

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

## 2.4 Making a changed value re-run the pipeline

Change only a CodeBuild *environment variable* and CloudFormation updates the
build project — but the pipeline resource is untouched, so nothing re-runs and
the service keeps the old value. That matters: `TRUSTSTORE` changes when the
certificate rotates.

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
charset-limited (IAM rejects the `?` in the trust store's `…?versionId=…` URI).
So resolved strings are hashed, and **tokens** — placeholders for values only
known at deploy time — get `Fn.base64`, whose output every tag accepts. Both
change exactly when the value does, which is all the tag is for.

`Token.is_unresolved` is the guard you need whenever synth-time Python has to
branch on a value that may not exist yet.

## 2.5 Verify

Nothing instantiates `CdkPipeline` yet, so the template is unchanged:

```
$ uv run python -c "from pycon2026.cdk_pipeline import CdkPipeline; print('ok')"
$ npx cdk synth
```

---

← [01 — Initialise the project](01-init-project.md)  ·  [03 — The TrustStore construct](03-trust-store.md) →
