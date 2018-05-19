# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/
"""Holder for resources that are held by a session"""

import cbor
import logging
import time
from messidge.broker.bases import SessionMinimal
from base64 import b64encode
from binascii import hexlify
from controller.tunnel import Tunnel
from model.cluster import Cluster
from model.container import Container


class Session(SessionMinimal):
    def __init__(self, rid, pk):
        super().__init__(rid, pk)
        logging.debug("Creating session rid: " + hexlify(rid).decode())
        self.dependent_containers = {}
        self.tunnels = {}  # a dict of tunnel_uuid to tunnel object
        self.clusters = {}
        self.last_heartbeat = time.time()

    def close(self, broker):
        logging.debug("Closing session rid: " + hexlify(self.rid).decode())
        # un-publish clusters
        if len(self.clusters) != 0:
            for cluster in self.clusters.values():
                logging.info("...garbage collecting cluster: " + cluster.uuid.decode())
            self.clusters = {}
            broker.proxy.rebuild()

        # disconnect tunnels
        for tunnel in list(self.tunnels.values()):
            logging.info("...garbage collecting tunnel: " + tunnel.uuid.decode())
            tunnel.disconnect()
        self.tunnels = {}

        # remove containers
        for container in self.dependent_containers.values():
            logging.info("...garbage collecting container: " + container.uuid.decode())
            try:
                node_rid = broker.node_pk_rid[container.node_pk]
                broker.send_cmd(node_rid, b'destroy_container', {'container': container.uuid,
                                                                 'session': self.rid,
                                                                 'inform': False})
            except KeyError:  # the node has not reappeared, we'll assume the container is gone too
                pass
        self.dependent_containers = {}

    def binary(self):
        return cbor.dumps({'pk': self.pk,
                           'containers': [c.as_dict() for c in self.dependent_containers.values()],
                           'tunnels': [t.as_dict() for t in self.tunnels.values()],
                           'clusters': [c.as_dict() for c in self.clusters.values()]})

    def state(self):
        return {'pk': b64encode(self.pk).decode(),
                'since_heartbeat': time.time() - self.last_heartbeat,
                'containers': {uuid.decode(): c.state() for uuid, c in self.dependent_containers.items()},
                'tunnels': {uuid.decode(): t.state() for uuid, t in self.tunnels.items()},
                'clusters': {uuid.decode(): c.state() for uuid, c in self.clusters.items()}}

    @staticmethod
    def from_binary(rid, binary):
        logging.info("Constructing session: " + hexlify(rid).decode())
        elements = cbor.loads(binary)
        sess = Session(rid, elements['pk'])
        for c in elements['containers']:
            ctr = Container.from_dict(c)
            sess.dependent_containers[ctr.uuid] = ctr
            logging.info("...dependent container: " + ctr.uuid.decode())
        for t in elements['tunnels']:
            tun = Tunnel.from_dict(t, sess)
            sess.tunnels[tun.uuid] = tun
            logging.info("...persisted tunnel: " + tun.uuid.decode())
        for c in elements['clusters']:
            clstr = Cluster.from_dict(c, sess.dependent_containers)
            sess.clusters[clstr.uuid] = clstr
            logging.info("...persisted cluster: " + clstr.uuid.decode())
        return sess

    def __repr__(self):
        return "<model.session.Session object at %x (containers=%d tunnels=%d clusters=%d)>" % \
               (id(self), len(self.dependent_containers), len(self.tunnels), len(self.clusters))
