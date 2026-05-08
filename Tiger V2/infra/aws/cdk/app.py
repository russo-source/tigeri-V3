import aws_cdk as cdk

from stacks.network_stack import NetworkStack
from stacks.data_stack import DataStack
from stacks.app_stack import AppStack

app = cdk.App()
env = cdk.Environment(region="ap-southeast-2")

network = NetworkStack(app, "TigeriNetwork", env=env)
data = DataStack(app, "TigeriData", vpc=network.vpc, env=env)
AppStack(
    app,
    "TigeriApp",
    vpc=network.vpc,
    db_secret=data.db_secret,
    documents_bucket=data.documents_bucket,
    env=env,
)

app.synth()
