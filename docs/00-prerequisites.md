# 00 — Prerequisites

## Tools

| Tool | Install |
|------|---------|
| [uv](https://docs.astral.sh/uv/) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js 18+ | [nodejs.org](https://nodejs.org) |
| AWS CDK CLI | `npm install -g aws-cdk` — or prefix every command with `npx aws-cdk` |
| AWS CLI v2 | [docs](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |

uv installs Python 3.12 for you. Check everything:

```
$ uv --version
$ npx aws-cdk --version
$ aws sts get-caller-identity
```

## AWS

Steps 01–06 only synthesize CloudFormation and need no credentials. Step 07
deploys, and needs an account that has been bootstrapped:

```
$ npx aws-cdk bootstrap aws://<account-id>/<region>
```

### The parent hosted zone

Step 04 delegates a subdomain of `pycon.foo`, which lives in another account.
That account holds a role named `CrossAccountZoneDelegationRole` your account
may assume in order to write the NS record. The instructor confirms your account
is on its trust policy.

Outside the workshop, change the three constants at the top of
[pycon2026/pycon_zone.py](../pycon2026/pycon_zone.py) to a zone you own — or
skip the zone entirely, since `Gateway` works without one.

### The GitHub connection

Step 02's pipelines pull source through an AWS **CodeConnections** connection.
Creating one needs a browser handshake, so it is done once, out of band, and its
ARN stored in SSM:

```
$ aws codeconnections create-connection \
      --provider-type GitHub --connection-name github-<you>
# then authorise it in the console: Developer Tools → Settings → Connections

$ aws ssm put-parameter --name /codestar-connection/github-<you> --type String \
      --value arn:aws:codeconnections:<region>:<account>:connection/<uuid>
```

The parameter name is `CONNECTION_ARN_PARAMETER` in
[pycon2026/cdk_pipeline.py](../pycon2026/cdk_pipeline.py). A connection left
`PENDING` never completes a pipeline run.

### Your own name

Replace `czarny` throughout with your own identifier. It becomes your subdomain
(`<you>.pycon.foo`) and your GitHub org for the two service repositories.

→ [01 — Initialise the project](01-init-project.md)
