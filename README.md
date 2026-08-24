
# Welcome to your CDK Python project!

This is a blank project for CDK development with Python.

The `cdk.json` file tells the CDK Toolkit how to execute your app.

This project uses [uv](https://docs.astral.sh/uv/) to manage the Python version,
the virtualenv and the dependencies. Install it first:

```
$ curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then create the virtualenv and install everything (including dev dependencies)
from the lockfile:

```
$ uv sync
```

uv creates the virtualenv in `.venv` and downloads the Python version pinned in
`.python-version` if it isn't already available. You don't need to activate the
virtualenv — prefix commands with `uv run` and uv keeps the environment in sync
automatically. If you prefer an activated shell, `source .venv/bin/activate`
(or `.venv\Scripts\activate.bat` on Windows) still works.

At this point you can now synthesize the CloudFormation template for this code.

```
$ uv run cdk synth
```

To run the unit tests:

```
$ uv run pytest
```

To add additional dependencies, for example other CDK libraries, use:

```
$ uv add some-library
```

and for dependencies only needed during development:

```
$ uv add --dev some-library
```

Both commands update `pyproject.toml`, resolve `uv.lock` and install into
`.venv`. Commit `uv.lock` so everyone gets the same versions.

## Useful commands

 * `uv sync`         install dependencies from the lockfile
 * `uv add <pkg>`    add a dependency
 * `uv run pytest`   run the unit tests
 * `cdk ls`          list all stacks in the app
 * `cdk synth`       emits the synthesized CloudFormation template
 * `cdk deploy`      deploy this stack to your default AWS account/region
 * `cdk diff`        compare deployed stack with current state
 * `cdk docs`        open CDK documentation

Enjoy!
