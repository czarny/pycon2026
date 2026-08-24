"""A trust store bundle of API Gateway client certificate PEMs, held on S3.

The client certificate is rotated every half year: the logical id carries a
`<year>H<half>` suffix, so a new certificate is created (and the old one
replaced) whenever the half changes.
"""

import datetime

from aws_cdk import (
    CustomResource,
    Duration,
    RemovalPolicy,
    aws_apigateway as apigateway,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_s3 as s3,
    custom_resources as cr,
)
from constructs import Construct

TRUST_STORE_KEY = "truststore.pem"

# Runs under the CDK custom-resource Provider framework, so it returns a plain
# dict rather than a signed CloudFormation response. boto3 ships in the Lambda
# Python runtime, so this needs no bundling and fits CloudFormation's 4 KB
# inline-code limit.
BUILDER_CODE = """
import boto3

apigateway = boto3.client("apigateway")
s3 = boto3.client("s3")


def handler(event, context):
    props = event["ResourceProperties"]
    bucket, key = props["Bucket"], props["Key"]
    physical_id = "s3://" + bucket + "/" + key

    if event["RequestType"] == "Delete":
        # The bucket itself is removed with the stack; nothing to undo here.
        return {"PhysicalResourceId": physical_id}

    pem = apigateway.get_client_certificate(
        clientCertificateId=props["ClientCertificateId"]
    )["pemEncodedCertificate"]

    response = s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=(pem.strip() + "\\n").encode(),
        ContentType="application/x-pem-file",
    )

    return {
        "PhysicalResourceId": physical_id,
        "Data": {"VersionId": response["VersionId"]},
    }
"""


class TrustStore(Construct):
    #: The certificate API Gateway presents to backends, verified against the bundle.
    client_certificate_id: str
    #: Bucket, key and object version as one string:
    #: s3://<bucket>/<key>?versionId=<version>. The s3:// scheme has no version
    #: component of its own, so this borrows the S3 REST API's `versionId` query
    #: parameter: consumers recover all three parts with urlparse + parse_qs.
    uri: str

    def __init__(self, scope: Construct, id: str) -> None:
        super().__init__(scope, id)

        now = datetime.datetime.now(datetime.timezone.utc)
        rotation_suffix = f"{now.year}H{1 if now.month <= 6 else 2}"

        client_certificate = apigateway.CfnClientCertificate(
            self,
            f"ClientCertificate{rotation_suffix}",
            description=f"{self.node.path} client certificate {rotation_suffix}",
        )
        self.client_certificate_id = client_certificate.ref

        bucket = s3.Bucket(
            self,
            "Bucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
        )

        builder = lambda_.Function(
            self,
            "BuilderFunction",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_inline(BUILDER_CODE),
            timeout=Duration.minutes(2),
            description=(
                "Fetches the API Gateway client certificate PEM and writes it "
                "to S3 as a trust store bundle"
            ),
        )
        builder.add_to_role_policy(
            iam.PolicyStatement(
                effect=iam.Effect.ALLOW,
                actions=["apigateway:GET"],
                resources=["*"],
            )
        )
        bucket.grant_write(builder)

        provider = cr.Provider(
            self,
            "BuilderProvider",
            on_event_handler=builder,
        )

        resource = CustomResource(
            self,
            "Bundle",
            service_token=provider.service_token,
            properties={
                "ClientCertificateId": self.client_certificate_id,
                "Bucket": bucket.bucket_name,
                "Key": TRUST_STORE_KEY,
            },
        )
        resource.node.add_dependency(bucket)

        version = resource.get_att_string("VersionId")
        self.uri = f"s3://{bucket.bucket_name}/{TRUST_STORE_KEY}?versionId={version}"
