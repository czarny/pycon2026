import aws_cdk as core
import aws_cdk.assertions as assertions

from pycon2026.stack import Stack


# example tests. To run these tests, uncomment this file along with the example
# resource in pycon2026/stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = Stack(app, "pycon2026")
    template = assertions.Template.from_stack(stack)


#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
