# Copyright (c) 2016-2018 David Preece - davep@polymath.tech, All rights reserved.
#
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted.
#
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
"""Creates keys and 'copy paste' bash script for a new node in this location"""

import sys
import boto3
import botocore.exceptions
import requests
import json
from broker import LaksaIdentity
from messidge import KeyPair
from model.model import Model
from model.state import ClusterGlobalState

init_template = """
mkdir -p /opt/20ft/etc
echo '%s' > /opt/20ft/etc/noodle-bootstrap
"""


def main():
    # basics
    aws = ClusterGlobalState(noserver=True)
    loc = Model(ClusterGlobalState.state_mountpoint)
    iden = LaksaIdentity()
    keys = KeyPair.new()

    try:
        # find a usable subnet id
        all_configs = iden.db.query("SELECT json FROM nodes", ())
        all_subnets = [json.loads(config[0])['subnet_id'] for config in all_configs]

        subnet_id = 2
        while subnet_id in all_subnets:
            subnet_id += 1

        # announce
        user_data = json.dumps({'bpk': aws.pk.decode(), 'pk': keys.public.decode(), 'sk': keys.secret.decode()})

        # try to launch via boto
        # http://boto3.readthedocs.io/en/latest/reference/services/ec2.html#EC2.ServiceResource.create_instances
        iam_id = aws.ssm.get_parameter('/20ft/node_instance_profile')['Parameter']['Value']
        ec2 = boto3.resource('ec2', region_name=aws.dynamic_data['region'])
        groups = {g.group_name: g for g in list(ec2.security_groups.all())}
        vpc_subnets = {sn.vpc_id: sn for sn in list(ec2.subnets.all())}
        my_security_group_name = requests.get('http://169.254.169.254/latest/meta-data/security-groups/').text
        my_security_group = groups[my_security_group_name]
        my_subnet = vpc_subnets[my_security_group.vpc_id]
        instances = ec2.create_instances(
                ImageId="ami-bccb08de",
                InstanceType='t2.medium',
                CreditSpecification={
                    'CpuCredits': 'unlimited'
                },
                BlockDeviceMappings=[
                    {
                        'DeviceName': '/dev/xvdb',
                        'Ebs': {
                            'VolumeSize': 32,  # zfs scratchpad, images etc
                            'VolumeType': 'gp2',
                        }
                    },
                ],
                KeyName=requests.get("http://169.254.169.254/latest/meta-data/public-keys/").text[2:],
                MaxCount=1,
                MinCount=1,
                Placement={
                    'AvailabilityZone': aws.dynamic_data['availabilityZone']
                },
                SecurityGroupIds=[
                    my_security_group.id
                ],
                SubnetId=my_subnet.id,
                IamInstanceProfile={
                    'Name': iam_id
                },
                UserData=user_data
        )
        print("Launched: " + instances[0].id)

    # not on aws
    except botocore.exceptions.ClientError:
        print("Initialise the new node with..." + init_template % user_data)

    # store the configuration
    iden.register_node(keys.public.decode(), json.dumps({"subnet_id": subnet_id, "passmarks": 4000}))

    iden.stop()
    aws.stop()


if __name__ == "__main__":
    main()
