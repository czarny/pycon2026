import aws_cdk as core
import aws_cdk.assertions as assertions

from pycon2026.pycon2026_stack import Pycon2026Stack

# example tests. To run these tests, uncomment this file along with the example
# resource in pycon2026/pycon2026_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = Pycon2026Stack(app, "pycon2026")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
