# 01 — Initialise the project

← [00 — Prerequisites](00-prerequisites.md)  ·  [02 — The CdkPipeline construct](02-cdk-pipeline.md) →

**Goal:** an empty CDK Python project, managed by uv, formatted by black, that
synthesizes.

## 1.1 Scaffold

`cdk init` needs an empty directory, and the directory name becomes the module
name.

```
$ mkdir pycon2026 && cd pycon2026
$ npx cdk init app --language python
```

Two generated files carry the wiring:

* **[app.py](https://github.com/czarny/pycon2026/blob/main/app.py)** constructs `cdk.App()`, instantiates the stack on it,
  and calls `app.synth()`. Everything hangs off that one tree.
* **[cdk.json](https://github.com/czarny/pycon2026/blob/main/cdk.json)** holds `"app"` — the command the CLI runs to produce
  the tree — and a block of **feature flags**, each opting into a behaviour
  change that would otherwise break existing stacks. Leave them alone.

## 1.2 Move to uv

Replace the generated requirements files with a lockfile-managed project:

```
$ rm requirements.txt requirements-dev.txt source.bat
$ echo "3.12" > .python-version

$ uv init --bare
$ uv add "aws-cdk-lib>=2.265.0,<3.0.0" "constructs>=10.5.0,<11.0.0"
$ uv add --dev "pytest==8.4.2" "black>=26.5.1"
```

Both caps matter: a major bump of either package is a breaking change. And
everything in CDK v2 — every AWS service — comes from the single `aws-cdk-lib`
package. Per-service packages are v1; do not add them.

Add to `pyproject.toml`:

```toml
[project]
requires-python = ">=3.10"

[tool.uv]
package = false          # an app, not a distributable library

[tool.black]
line-length = 120        # CDK code nests deeply; 88 is too narrow
target-version = ["py312"]
```

Point the CDK CLI at uv, in `cdk.json`:

```json
{
  "app": "uv run python3 app.py"
}
```

`uv run` re-syncs the environment before every invocation, so `cdk synth` can
never run against a stale virtualenv. You never activate `.venv`. Commit
`uv.lock`.

## 1.3 Trim the generated stack

`cdk init` leaves a commented-out SQS queue behind. Delete it:

```python
# pycon2026/stack.py
import aws_cdk as cdk
from constructs import Construct

class Stack(cdk.Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
```

The generated names were `pycon2026_stack.py` / `Pycon2026Stack`; the module
path already says `pycon2026`, so this repo renames both. Keep
[app.py](https://github.com/czarny/pycon2026/blob/main/app.py) in sync — but leave the *construct id* `"Pycon2026Stack"`
alone, since that is the CloudFormation stack name.

## 1.4 Verify

```
$ uv run black .
$ uv run pytest
$ npx cdk synth
```

Open `cdk.out/Pycon2026Stack.template.json`. An empty stack is not empty — it
carries metadata and the bootstrap contract's rules. That file is the only thing
CloudFormation ever sees; everything from here on is a program that prints it.

`cdk.out/` is gitignored: synthesized output is a build artifact.

---

← [00 — Prerequisites](00-prerequisites.md)  ·  [02 — The CdkPipeline construct](02-cdk-pipeline.md) →
