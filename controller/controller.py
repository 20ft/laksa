# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/
"""Commands issued to the master"""

# The broker is single threaded so these must all be non-blocking  ... ish
# the presence of msg.params is checked by check_basic_properties

import logging
import time
import threading
import socket
from sqlite3 import IntegrityError
from base64 import b64encode
from binascii import hexlify
from DNS.lazy import dnslookup
from DNS.Base import ServerError
from messidge.broker.broker import BrokerMessage
from controller.tunnel import Tunnel
from controller.volumes import Volume
from model.container import Container
from model.domain import Domain
from model.cluster import Cluster


class Controller:
    def __init__(self, broker, model, network, images):
        self.broker = broker
        self.model = model
        self.network = network
        self.images = images
        self.last_heartbeat = time.time()

    def check_heartbeat(self):
        # is it that time?
        tme = time.time()
        # check to ensure the sessions are live
        for rid, sess in list(self.model.sessions.items()):
            if tme - sess.last_heartbeat >= 120:
                logging.info("Session timed out: " + hexlify(sess.rid).decode())
                sess.close(self.broker)
                self.broker.disconnect_for_rid(sess.rid)

    def _update_stats(self, msg):
        """Receiving updated performance counters from a node"""
        try:
            pk = self.broker.node_rid_pk[msg.rid]
        except KeyError:
            logging.warning("Update stats called by an unknown node connection: " + hexlify(msg.rid).decode())
            return
        try:
            node = self.model.nodes[pk]
        except KeyError:
            logging.warning("Could not relate public key to a node: " + b64encode(pk).decode())
            return
        if node is None:
            logging.warning("model.nodes is None for: " + b64encode(pk).decode())
            return

        # update
        old_stats = node.perf_counters
        try:
            node.update_stats(msg.params['stats'])
        except KeyError:
            logging.warning("Node sent broken stats: " + str(msg.params['stats']))

        # did it change?
        if old_stats == node.perf_counters:
            return

        # update server weights
        self.broker.proxy.rebuild()

        # distribute to the sessions
        for rid in list(self.model.sessions.keys()):
            self.broker.send_cmd(rid, b'update_stats', {'node': pk, 'stats': msg.params['stats']})

    def _wait_tcp(self, msg):
        """Returns the message when L4 is up on a particular container and port,
        a blocking operation so spawns a thread"""
        def _impl_wait_tcp(c, m):
            attempts = 0
            while True:
                time.sleep(0.5)
                try:
                    s = socket.create_connection((c.ip, m.params['port']))
                    m.reply()
                    return
                except (ConnectionRefusedError, OSError, TimeoutError):
                    attempts += 1
                    if attempts == 60:
                        m.reply({'exception': 'Could not connect'})
                        return

        ctr = self._ensure_valid_container(msg.rid, msg.params['container'])
        t = threading.Thread(target=_impl_wait_tcp, args=(ctr, msg),
                             name="Waiting for TCP on: " + msg.params['container'].decode())
        t.start()

    def _inform_external_ip(self, msg):
        """Receiving a node's external IP, send topology to all nodes"""
        pk = self.broker.node_rid_pk[msg.rid]
        self.model.nodes[pk].external_ip = msg.params['ip']
        self.broker.node_topology()

        # did we get an amazon id at the same time?
        if 'instance_id' in msg.params:
            self.model.nodes[pk].instance_id = msg.params['instance_id']

    def _upload_requirements(self, msg):
        """Given a list of layers, return a list of the ones that need uploading"""
        to_be_uploaded = self.broker.images.upload_requirements(msg.params['layers'])
        msg.reply(to_be_uploaded)

    def _upload_slab(self, msg):
        """Delivering a piece of layer"""
        log_msg = self.broker.images.upload_slab(msg.params['sha256'], msg.params['slab'], msg.bulk)
        msg.reply({'log': log_msg})

    def _upload_complete(self, msg):
        """The layer upload is complete"""
        log_msg = self.broker.images.upload_complete(msg.params['sha256'])
        logging.info(log_msg)
        msg.bulk = b''
        msg.reply({'log': log_msg})

    def _allocate_ip(self, msg):
        """Called by a node - allocate an ip address in the right subnet"""
        node_pk = self.broker.node_rid_pk[msg.rid]
        node = self.model.nodes[node_pk]
        msg.reply({'ip': self.model.next_ip(int(node.subnet_id)), 'container': msg.params['container']})

    def _approve_tag(self, msg):
        """Ensure a proposed advertised tag is going to be OK"""
        # Don't need this for volumes because volume creation checks this already
        # and container creation is async, hence approving it first
        if self.model.containers.will_clash(msg.params['user'], msg.uuid, msg.params['tag']):
            raise ValueError("Tag is already being used")
        else:
            msg.reply()  # didn't raise an error so we're all good

    def _create_tunnel(self, msg):
        """Create a tunnel onto a container"""
        sess = self._ensure_valid_session(msg.rid)
        ctr = self._ensure_valid_container(msg.rid, msg.params['container'])
        tunnel = Tunnel(msg.uuid, sess, self.broker, self.broker.loop,
                        ctr.ip, msg.params['port'], msg.params['timeout'])
        sess.tunnels[msg.uuid] = tunnel
        self.model.update_session_record(sess)

    def _destroy_tunnel(self, msg):
        """Destroy a tunnel onto a container"""
        try:
            sess = self._ensure_valid_session(msg.rid)
            tun = sess.tunnels[msg.params['tunnel']]
            tun.disconnect()
            del sess.tunnels[tun.uuid]
            self.model.update_session_record(sess)
            logging.info("Destroyed tunnel uuid: " + tun.uuid.decode())
        except KeyError:
            raise ValueError("Unknown session or tunnel")

    def _to_proxy(self, msg):
        """Get the tunnel to send data to the container"""
        try:
            sess = self._ensure_valid_session(msg.rid)
            sess.tunnels[msg.params['tunnel']].forward(msg)
        except KeyError:
            pass

    def _close_proxy(self, msg):
        """Done with the tunnel"""
        try:
            sess = self._ensure_valid_session(msg.rid)
            sess.tunnels[msg.params['tunnel']].close_proxy(msg.params['proxy'])
        except KeyError:
            # sometimes we close this end, which closes the other end and sends a message telling this end to close
            pass

    def _cache_description(self, msg):
        self.model.create_update_description_record(msg.params['user'],
                                                    msg.params['image_id'],
                                                    msg.params['description'])
        logging.debug("Cached description for: " + msg.params['image_id'])

    def _retrieve_description(self, msg):
        full_id = b64encode(msg.params['user']).decode() + msg.params['image_id']
        if full_id in self.model.descriptions:
            logging.debug("Cache hit on descriptions for: " + msg.params['image_id'])
            msg.reply(results={'description': self.model.descriptions[full_id]})
        else:
            logging.debug("Cache miss on descriptions for: " + msg.params['image_id'])
            msg.reply()

    def _dependent_container(self, msg):
        # will there be a namespace clash?
        if self.model.containers.will_clash(msg.params['cookie']['user'],
                                            msg.params['container'],
                                            msg.params['cookie']['tag']):
            logging.info("Tried to register a dependent container but there would be a namespace collision.")
            self.broker.send_cmd(msg.rid, b'destroy_container', {'container': msg.params['container'],
                                                                 'inform': False})
            return

        # create the container object
        try:
            ctr = Container(msg.params['cookie']['user'],
                            msg.params['container'],
                            msg.params['cookie']['tag'],
                            msg.params['cookie']['session'],
                            msg.params['node_pk'],
                            msg.params['ip'],
                            msg.params['volumes'])
            sess = self.model.sessions[msg.params['cookie']['session']]
            sess.dependent_containers[ctr.uuid] = ctr
            self.model.containers.add(ctr)  # this is the tagged collection
            self.model.update_session_record(sess)
            logging.info("Registered a dependency: %s -> %s" %
                         (hexlify(msg.params['cookie']['session']).decode(),
                          msg.params['container'].decode()))
        except KeyError:
            # if trying to register but the session has disappeared already, tell the node to destroy the container
            logging.info("Tried to register a dependent container to a session that has already gone, destroying.")
            self.broker.send_cmd(msg.rid, b'destroy_container', {'container': msg.params['container'],
                                                                 'inform': False})  # don't inform because session gone
            return

    def _destroyed_container(self, msg):
        logging.info("A dependent container has been destroyed: " + msg.params['container'].decode())
        self._impl_destroyed_container(msg.params['container'], msg.params['ip'] if 'ip' in msg.params else None)

    def _impl_destroyed_container(self, uuid, ip):
        # release the ip but not using the one associated with the container in self.model because it might be missing
        if ip is not None:
            self.model.release_ip(ip)

        # try to find (and delete) the container
        try:
            ctr = self.model.containers[uuid]
            self.model.containers.remove(ctr)
        except KeyError:
            logging.debug("Informed of destroyed container but couldn't find: " + uuid.decode())
            return

        # can we associate it with a session?
        try:
            sess = self.model.sessions[ctr.session_rid]
            del sess.dependent_containers[uuid]
            self.model.update_session_record(sess)
        except KeyError:
            logging.debug("Session or dependency has disappeared before destroying: ctr-" + uuid.decode())

    def _create_volume(self, msg):
        """Create a local zfs volume to be shared with containers"""
        if self.model.volumes.will_clash(msg.params['user'], msg.uuid, msg.params['tag']):
            raise ValueError("Volume tag is already being used")
        vol = Volume.create(msg.params['user'], msg.uuid, msg.params['tag'], msg.params['async'])
        self.model.volumes.add(vol)
        msg.reply()

        # let the clients know
        for rid in list(self.model.sessions.keys()):
            if rid != msg.rid:
                self.broker.send_cmd(rid, b'volume_created', {'volume': msg.uuid, 'tag': msg.params['tag']})

    def _destroy_volume(self, msg):
        # is it mounted in any containers?
        for sess in self.model.sessions.values():
            for ctr in sess.dependent_containers.values():
                if msg.params['volume'] in ctr.volumes:
                    raise ValueError("Volume is mounted in a container: " + ctr.uuid.decode())

        # destroy
        vol = self._ensure_valid_volume(msg)
        vol.destroy()
        self.model.volumes.remove(vol)
        msg.reply()

        # let the clients know
        for rid in list(self.model.sessions.keys()):
            if rid != msg.rid:
                self.broker.send_cmd(rid, b'volume_destroyed', {'volume': msg.params['volume']})

    def _snapshot_volume(self, msg):
        self._ensure_valid_volume(msg).snapshot()

    def _rollback_volume(self, msg):
        self._ensure_valid_volume(msg).rollback()

    def _prepare_domain(self, msg):
        # shedding aged domains will have happened already as part of the resource offer, dict entry will exist
        domain = msg.params['domain']
        if domain is None:
            raise ValueError("Need a domain name")
        sess = self._ensure_valid_session(msg.rid)
        try:
            # see if the domain is already owned by us in some way
            d = self.model.domains[sess.pk][domain]
            if d.is_valid():
                raise ValueError('You have already claimed this domain.')
            else:
                raise ValueError('You are already trying to claim this domain, the token is ' + d.token)
        except KeyError:
            pass

        # try to create a new domain, see if the db borks
        obj = Domain(domain, msg.uuid, sess.pk)
        try:
            self.model.create_domain_record(obj, sess)  # may throw so domain won't be added to dict
            self.model.domains[sess.pk][domain] = obj
        except IntegrityError:
            logging.debug("Trying to prepare domain, shedding aged domains: " + msg.params['domain'])
            self.model.shed_aged_domains()  # and try again
            try:
                self.model.create_domain_record(obj, sess)
                self.model.domains[sess.pk].add(obj)
                logging.debug("Managed to prepare domain.")
            except IntegrityError:
                logging.debug("Shedding aged domains failed to free.")
                raise ValueError('This domain is already claimed or in the process of being claimed')

        logging.info("User (%s) prepared to claim domain: %s" % (b64encode(sess.pk).decode(), domain))
        msg.reply({'token': obj.token})

    def _claim_domain(self, msg):
        # TODO: A blocking DNS call right in the middle of the message loop is a terrible idea.
        domain = msg.params['domain']
        if domain is None:
            raise ValueError("Need a domain name")
        sess = self._ensure_valid_session(msg.rid)
        try:
            dom = self.model.domains[sess.pk][domain]
        except KeyError:
            raise ValueError("Domain is not in the process of being claimed by you")
        if dom.is_valid():
            raise ValueError("Domain has already been claimed")

        # look it up, then
        token_url = 'tf-token.' + domain
        try:
            token_from_dns = dnslookup(token_url, 'txt')
        except ServerError:
            raise ValueError("Did not find a TXT record for " + token_url)
        if len(token_from_dns) != 1 or len(token_from_dns[0]) != 1:
            raise ValueError("DNS token was malformed (more than one txt record?)")
        if token_from_dns[0][0] != dom.token:
            raise ValueError("DNS returned the wrong token, needed " + dom.token.decode())
        dom.mark_as_valid()
        self.model.update_domain_record(dom)
        logging.info("User (%s) successfully claimed domain: %s" % (b64encode(sess.pk).decode(), domain))
        msg.reply()

    def _make_domain_global(self, msg):
        dom = self._ensure_valid_domain(msg.rid,  msg.params['domain'])
        dom.mark_as_global()
        self.model.add_global_domain(dom)
        self.model.update_domain_record(dom)
        logging.info("Domain made global: " + msg.params['domain'])
        msg.reply()

    def _make_domain_private(self, msg):
        dom = self._ensure_valid_domain(msg.rid, msg.params['domain'])
        dom.mark_as_global(False)
        self.model.remove_global_domain(dom)
        self.model.update_domain_record(dom)
        logging.info("Domain made private: " + msg.params['domain'])
        msg.reply()

    def _release_domain(self, msg):
        domain = msg.params['domain']
        if domain is None:
            raise ValueError("Need a domain name")
        sess = self._ensure_valid_session(msg.rid)
        try:
            del self.model.domains[sess.pk][domain]
            self.model.delete_domain_record(domain)
        except KeyError:
            raise ValueError("Domain has not been either prepared or claimed by you")
        logging.info("User (%s) released domain: %s" % (b64encode(sess.pk).decode(), domain))
        msg.reply()

    def _publish_web(self, msg):
        # does this user own this domain?
        sess = self._ensure_valid_session(msg.rid)
        domains = self.model.global_domains
        try:
            for d in self.model.domains[sess.pk].values():
                domains[d.domain] = d
        except KeyError:
            pass

        # is it valid?
        try:
            domain = domains[msg.params['domain']]
            if not domain.is_valid():
                raise ValueError("Domain setup has not been completed")
        except KeyError:
            raise ValueError("Domain is not valid for this user: " + msg.params['domains'])

        # is someone else using this fqdn already?
        fqdn = msg.params['subdomain'] + msg.params['domain']
        for cluster in self.model.all_clusters():
            if cluster.fqdn() == fqdn:
                raise ValueError("FQDN is being used by another session")

        # are the container uuids correct
        try:
            containers = [self.model.containers[uuid] for uuid in msg.params['containers']]
        except KeyError:
            raise ValueError("Incorrect uuid in containers")

        # Note that the containers are already "dependent" containers in the session so no additional tracking
        cluster = Cluster(msg.uuid,
                          msg.params['domain'], msg.params['subdomain'], msg.params['ssl'], msg.params['rewrite'],
                          containers)
        sess.clusters[msg.uuid] = cluster
        self.model.update_session_record(sess)
        self.broker.proxy.rebuild()
        logging.info("Published cluster (%s) to: %s" % (msg.uuid.decode(), fqdn))
        msg.reply()

    def _unpublish_web(self, msg):
        # correct user?
        sess = self._ensure_valid_session(msg.rid)
        self._ensure_valid_cluster(sess, msg.params['cluster'])

        # all good
        del sess.clusters[msg.params['cluster']]
        self.model.update_session_record(sess)
        self.broker.proxy.rebuild()
        logging.info("Unpublished cluster: " + msg.params['cluster'].decode())

    def _add_to_cluster(self, msg):
        sess = self._ensure_valid_session(msg.rid)
        clstr = self._ensure_valid_cluster(sess, msg.params['cluster'])
        ctr = self._ensure_valid_container(msg.rid, msg.params['container'])
        if ctr.uuid not in clstr.containers:
            clstr.containers[ctr.uuid] = ctr
            self.model.update_session_record(sess)
            self.broker.proxy.rebuild()
            logging.info("Added (%s) to cluster: %s" % (msg.params['container'].decode(),
                                                        msg.params['cluster'].decode()))
        msg.reply()

    def _remove_from_cluster(self, msg):
        sess = self._ensure_valid_session(msg.rid)
        clstr = self._ensure_valid_cluster(sess, msg.params['cluster'])
        ctr = self._ensure_valid_container(msg.rid, msg.params['container'])
        if ctr.uuid in clstr.containers:
            del clstr.containers[ctr.uuid]
            self.model.update_session_record(sess)
            self.broker.proxy.rebuild()
            logging.info("Removed (%s) form cluster: %s" % (msg.params['container'].decode(),
                                                            msg.params['cluster'].decode()))

    def _heartbeat(self, msg):
        # mark the session as being live
        sess = None
        try:
            sess = self._ensure_valid_session(msg.rid)
        except KeyError:
            logging.warning("A heartbeat message arrived for a session we thought was gone: " +
                            hexlify(msg.rid).decode())
            return
        sess.last_heartbeat = time.time()

        # heartbeat the containers in the session
        for uuid, ctr in sess.dependent_containers.items():
            try:
                node_rid = self.broker.node_pk_rid[ctr.node_pk]
                BrokerMessage.send_socket(self.broker.skt, node_rid, b'',
                                          b'heartbeat_container', b'', {'container': uuid})
            except KeyError:
                # node is temporarily (hopefully) offline
                logging.warning("Tried to heartbeat a container but couldn't find the node: "
                                + b64encode(ctr.node_pk).decode())

    def _ping(self, msg):
        msg.reply()

    def _ensure_valid_session(self, rid):
        try:
            return self.model.sessions[rid]
        except KeyError:
            raise ValueError("Command does not appear to have come from a valid session")

    def _ensure_valid_container(self, session, uuid):  # session has already been validated
        sess = self._ensure_valid_session(session)
        try:
            return sess.dependent_containers[uuid]
        except KeyError:
            raise ValueError("Command does not appear to be addressed to a valid container")

    def _ensure_valid_volume(self, msg):
        if msg.params['volume'] not in self.model.volumes:
            logging.info("User (%s) attempted to access a non-existent volume: %s" %
                         (b64encode(msg.params['user']).decode(), str(msg.params['volume'].decode())))
            raise ValueError("Referenced a non-existent volume: " + msg.params['volume'].decode())
        vol = self.model.volumes[msg.params['volume']]
        # Volume being owned by the wrong user returns same error to avoid leaking information
        if vol.user != msg.params['user']:
            logging.warning("User (%s) attempted to access a volume owned by someone else: %s" %
                            (b64encode(msg.params['user']).decode(), str(msg.params['volume'].decode())))
            raise ValueError("Referenced a non-existent volume: " + msg.params['volume'].decode())
        return vol

    def _ensure_valid_domain(self, session, domain):
        sess = self._ensure_valid_session(session)
        try:
            return self.model.domains[sess.pk][domain]
        except KeyError:
            raise ValueError("Not apparently one of your domains")

    def _ensure_valid_cluster(self, sess, uuid):
        try:
            return sess.clusters[uuid]
        except KeyError:
            raise ValueError("Cluster does not exist")



    # commands are: {b'command': (['list', 'essential, 'params'], needs_reply, node_only),....}
    # update_volumes and upload_requirements get passed a list, hence no check for parameters
    commands = {b'inform_external_ip': (['ip'], False, True),
                b'update_stats': (['stats'], False, True),

                b'wait_tcp': (['container', 'port'], True, False),
                b'create_tunnel': (['container', 'port', 'timeout'], False, False),
                b'destroy_tunnel': (['tunnel'], False, False),
                b'to_proxy': (['tunnel', 'proxy'], False, False),
                b'close_proxy': (['tunnel', 'proxy'], False, False),

                b'cache_description': (['image_id', 'description'], False, False),
                b'retrieve_description': (['image_id'], True, False),

                b'upload_requirements': ([], True, False),
                b'upload_slab': (['sha256', 'slab'], False, False),
                b'upload_complete': (['sha256'], False, False),

                b'create_volume': (['tag', 'async'], True, False),
                b'destroy_volume': (['volume'], True, False),
                b'snapshot_volume': (['volume'], False, False),
                b'rollback_volume': (['volume'], False, False),

                b'approve_tag': (['user', 'tag'], True, False),
                b'allocate_ip': (['container'], True, True),
                b'dependent_container': (['container', 'node_pk', 'ip', 'cookie'], False, True),
                b'destroyed_container': (['container', 'node_pk'], False, True),

                b'prepare_domain': (['domain'], True, False),
                b'claim_domain': (['domain'], True, False),
                b'make_domain_global': (['domain'], True, False),
                b'make_domain_private': (['domain'], True, False),
                b'release_domain': (['domain'], True, False),

                b'publish_web': (['domain', 'subdomain', 'rewrite', 'ssl', 'containers'], True, False),
                b'unpublish_web': (['cluster'], False, False),
                b'add_to_cluster': (['cluster', 'container'], True, False),
                b'remove_from_cluster': (['cluster', 'container'], False, False),

                b'heartbeat': ([], False, False),
                b'ping': ([], True, False)}

    def __repr__(self):
        return "<controller.controller.Controller object at %x>" % id(self)
