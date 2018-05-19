# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/
"""Internal representation of a Node"""

import json
import math
from base64 import b64encode
from messidge.broker.bases import NodeMinimal


class Node(NodeMinimal):
    def __init__(self, pk, msg, config_string):
        super().__init__(pk, msg, config_string)
        config = json.loads(config_string)  # the config string is held in the db as json for sanity's sake
        self.perf_counters = {'cpu': 1000, 'memory': 1000, 'paging': 0, 'ave_start_time': 0}
        self.passmarks = config['passmarks'] if 'passmarks' in config else 10000
        self.subnet_id = config['subnet_id']
        self.external_ip = None
        self.instance_id = None

    def update_stats(self, new):
        self.perf_counters = new
        self.perf_counters['cpu'] *= (self.passmarks * 0.01)  # scale % to 0-1 then multiply by passmarks
        self.perf_counters['cpu'] = int(self.perf_counters['cpu'])
        self.perf_counters['memory'] //= 1024  # in MB

    def weight(self):
        return math.floor(self.perf_counters['cpu'] / 100) + 10

    def state(self):  # ip gets added by the inspection server itself
        return {'subnet_id': self.subnet_id,
                'external_ip': self.external_ip,
                'instance_id': self.instance_id,
                'pk': b64encode(self.pk).decode(),
                'weight': self.weight(),
                'perf_counters': self.perf_counters}

    def __repr__(self):
        return "<model.node.Node object at %x (subnet_id=%d)>" % (id(self), self.subnet_id)

