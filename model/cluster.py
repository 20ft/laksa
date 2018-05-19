# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/

import os
from base64 import b64encode, b64decode


class Cluster:
    """A collection of containers (for publishing to an endpoint)"""
    def __init__(self, uuid, domain, subdomain, ssl, rewrite, containers):
        self.uuid = uuid
        self.domain = domain
        self.subdomain = subdomain
        self.ssl = ssl
        self.rewrite = rewrite
        self.containers = {c.uuid: c for c in containers}

        if ssl is not None:
            with open(self.fqdn() + '.ssl', 'w') as ssl_file:
                ssl_file.write(self.ssl)

    def __del__(self):
        if self.ssl is not None:
            os.remove(self.fqdn() + '.ssl')

    def fqdn(self):
        return self.subdomain + self.domain

    def as_dict(self):
        return {"uuid": self.uuid,
                "domain": self.domain,
                "subdomain": self.subdomain,
                "ssl": b64encode(self.ssl.encode()) if self.ssl is not None else None,
                "rewrite": self.rewrite,
                "containers": [c for c in self.containers.keys()]}

    def state(self):
        return {"fqdn": self.subdomain + self.domain,
                "ssl": (self.ssl is not None),
                "rewrite": self.rewrite,
                "containers": [c.decode() for c in self.containers.keys()]}

    @staticmethod
    def from_dict(desc, containers):  # pass containers so we can link to the actual objects
        ctrs = [ctr for ctr in containers.values() if ctr.uuid in desc['containers']]
        return Cluster(desc['uuid'], desc['domain'], desc['subdomain'],
                       b64decode(desc['ssl']).decode() if desc['ssl'] is not None else None, desc['rewrite'], ctrs)

    def __repr__(self):
        return "<model.cluster.Cluster object at %x (%s:%s containers=%d)>" % \
               (id(self), self.subdomain + self.domain, self.rewrite, len(self.containers))
