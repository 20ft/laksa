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

# controller.network is symlinked over from noodle

import os
from subprocess import call
from messidge.broker.broker import Broker as BrokerBase
from messidge.broker.identity import Identity
from messidge import KeyPair
from model.state import ClusterGlobalState
from model.node import Node
from model.session import Session
from model.model import Model
from controller.controller import Controller
from controller.images import Images
from controller.inspect import LaksaInspection
from controller.haproxy import HAProxy
from controller.network import Network


class Broker(BrokerBase):
    def __init__(self):
        # raise my priority
        os.setpriority(os.PRIO_PROCESS, 0, -15)

        # HAProxy sometimes gets annoyed
        call(['systemctl', 'restart', 'haproxy'])

        # blanks so we can always call stop
        self.model = None
        self.env = None
        self.inspect = None

        # get the base class up
        try:
            self.env = ClusterGlobalState()
            self.keys = KeyPair(public=self.env.pk, secret=self.env.sk)
            self.model = Model(self.env.state_mountpoint)
            self.network = Network()
            self.images = Images()
            self.controller = Controller(self, self.model, self.network, self.images)
            super().__init__(self.keys, self.model, Node, Session, self.controller,
                             identity_type=LaksaIdentity,
                             pre_run_callback=self.pre_run,
                             session_recovered_callback=self.session_recovered,
                             session_destroy_callback=self.session_destroyed,
                             node_create_callback=self.node_created,
                             node_destroy_callback=self.node_destroyed,
                             forwarding_insert_callback=self.model.set_forwarding_record,
                             forwarding_evict_callback=self.model.remove_forwarding_record
                             )
            self.proxy = HAProxy(self.model)
            self.inspect = LaksaInspection(self)
        except BaseException:
            self.stop()
            raise

    def stop(self):
        super().stop()

        # clean up firewall
        for node in self.model.nodes.values():
            Network.allow_incoming_from_node(node.subnet_id, reverse=True)
        Network.drop_incoming_from_underlay(reverse=True)

        # stop objects that have background threads
        self.model.close()
        self.inspect.stop()
        self.env.stop()

    def pre_run(self):
        # Register checking heartbeating from the controller
        self.loop.register_on_idle(self.controller.check_heartbeat)

        # Any persisted tunnels need hooking into the broker and loop
        for tunnel in self.model.all_tunnels():
            tunnel.set_broker_and_loop(self, self.loop)

        # Firewall against the underlay
        Network.drop_incoming_from_underlay()

    def session_recovered(self, session, old_rid, new_rid):
        # ensure the backlink from containers is correct
        for uuid in session.dependent_containers.keys():
            self.model.containers[uuid].session_rid = new_rid

        # fix up the forwarding table
        for uuid, rid in list(self.model.long_term_forwards.items()):
            if rid == old_rid:
                self.model.long_term_forwards[uuid] = new_rid
                self.model.set_forwarding_record(uuid, new_rid)

    def session_destroyed(self, rid):
        self.model.delete_session_record(rid)

    def node_created(self, pk):
        # let the clients know
        for rid in list(self.model.sessions.keys()):
            self.send_cmd(rid, b'node_created', {'node': pk})
        # topology is recreated when the node sends its' external IP

    def node_destroyed(self, pk):
        # let the clients know
        for rid in list(self.model.sessions.keys()):
            self.send_cmd(rid, b'node_destroyed', {'node': pk})

        # let the individual containers know
        for ctr in self.model.containers.values():
            self.controller._impl_destroyed_container(ctr.uuid, ctr.ip)

        # advertise new topology
        self.node_topology()

    def node_topology(self):
        # calculate and publish the new network topology
        topology = self.model.network_topology()
        add_subnets, remove_subnets = self.network.topology(topology)
        for sn in add_subnets:
            Network.allow_incoming_from_node(sn)
        for sn in remove_subnets:
            Network.allow_incoming_from_node(sn, reverse=True)
        for this_rid in self.node_rid_pk.keys():
            self.send_cmd(this_rid, b'network_topology', {"topology": topology})


class LaksaIdentity(Identity):
    def __init__(self):
        super().__init__('/opt/20ft/laksa/state/')
