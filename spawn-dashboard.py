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
"""Creates a dashboard for the current infrastructure"""

import sys
import boto3
import botocore.exceptions
import logging
import requests
import json
from awsornot import dynamic_data_or_none
from model.state import ClusterGlobalState


def main():
    dynamic = dynamic_data_or_none()
    if dynamic is None:
        logging.error("This only works on EC2")
        exit(1)

    # get the state
    http = requests.get('http://127.0.0.1:1024')
    state = json.loads(http.text)

    # single value metrics
    sv_metrics = [
        [
          "AWS/EC2",
          "CPUCreditBalance",
          "InstanceId",
          dynamic['instanceId'],
          {
            "label": "broker"
          }
        ]
    ]

    for node in state['rid_to_node'].values():
        single_node = ["...", node['instance_id'], {"label": "node:" + node['instance_id'][2:6]}]
        sv_metrics.append(single_node)

    # graphed metrics
    last_first_four = (None, None, None, None)
    graph_metrics = []
    for node in state['rid_to_node'].values():
        for metric, right in (('FreeCPU', False), ('AveStartupTime', True), ('Containers', True)):
            this_first_four = ('20ft Nodes', metric, 'InstanceID', node['instance_id'])
            four = ["." if this_first_four[i] == last_first_four[i] else this_first_four[i] for i in range(0, 4)]
            last_first_four = this_first_four
            label = {'label': metric + ':' + node['instance_id'][2:6], 'period': 60}
            if right:
                label['yAxis'] = 'right'
            four.append(label)
            graph_metrics.append(four)

    widgets = [
        {
            "type": "metric",
            "x": 0,
            "y": 0,
            "width": 24,
            "height": 6,
            "properties": {
                "title": "Node Performance",
                "view": "timeSeries",
                "region": dynamic['region'],
                "stacked": False,
                "period": 60,
                "yAxis": {
                    "left": {
                        "min": 0,
                        "max": 100
                    },
                    "right": {
                        "min": 0,
                        "max": 20
                    }
                },
                "metrics": graph_metrics
            }
        },
        {
            "type": "metric",
            "x": 0,
            "y": 6,
            "width": 24,
            "height": 3,
            "properties": {
                "view": "singleValue",
                "region": dynamic['region'],
                "metrics": sv_metrics
            }
        }
    ]
    # translate into an object that represents the dashboard

    # spawn the dashboard
    dash = {
        "widgets": widgets,
        "region": dynamic['region']
    }
    client = boto3.client('cloudwatch', region_name=dynamic['region'])
    client.put_dashboard(
        DashboardName="tfnz",
        DashboardBody=json.dumps(dash)
    )


if __name__ == "__main__":
    main()
