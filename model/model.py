# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/
"""The model, holds state for everything. """

# Laksa thinks in terms of sessions, not users, and uses users basically as an authentication and filtering parameter


import logging
import random
import cbor
from base64 import b64encode
from tfnz import TaggedCollection
from controller.network import Network
from litecache.cache import SqlCache
from messidge.broker.bases import ModelMinimal
from model.session import Session
from model.domain import Domain
from controller.volumes import Volume

init_domains = """
CREATE TABLE domains (domain TEXT NOT NULL UNIQUE, token TEXT, attempted INTEGER, user TEXT, global BOOLEAN DEFAULT 0);
"""

init_descriptions = """
CREATE TABLE descriptions (full_id TEXT NOT NULL UNIQUE, cbor BLOB NOT NULL);
"""

init_state = """
CREATE TABLE sessions (rid TEXT NOT NULL PRIMARY KEY, cbor BLOB NOT NULL);
CREATE TABLE forwarding (key BLOB NOT NULL PRIMARY KEY, value BLOB NOT NULL);
"""


class Model(ModelMinimal):
    def __init__(self, state_directory):
        super().__init__()
        # db's up and going
        self.state_db = SqlCache(state_directory, 'state', init_state)
        self.domains_db = SqlCache(state_directory, 'domains', init_domains)
        self.descriptions_db = SqlCache(state_directory, 'descriptions', init_descriptions)

        # initialise sessions, containers and ip allocations
        binary_sessions = self.state_db.query("SELECT rid,cbor FROM sessions")
        self.sessions = {rid: Session.from_binary(rid, binary) for rid, binary in binary_sessions}
        self.containers = TaggedCollection()
        self.allocations = set()
        for session in self.sessions.values():
            for uuid, container in session.dependent_containers.items():
                self.containers.add(container)
                self.allocations.add(container.ip)

        # fetch the forwarding table
        forwarding = self.state_db.query("SELECT key,value FROM forwarding")
        for forward in forwarding:
            self.long_term_forwards[forward[0]] = forward[1]

        # volumes
        self.volumes = Volume.all()

        # domain ownership
        self.domains = {}
        self.global_domains = {}
        domains = self.domains_db.query("SELECT domain,token,attempted,user,global FROM domains")
        for domain, token, attempted, user, gbl in domains:
            dom_obj = Domain(domain, token, user, attempted, gbl)
            if user not in self.domains:
                self.domains[user] = {}  # map domain name to domain object
            self.domains[user][domain] = dom_obj
            if gbl:
                self.global_domains[domain] = dom_obj

        # descriptions
        descriptions = self.descriptions_db.query("SELECT full_id,cbor FROM descriptions")
        self.descriptions = {d[0]: cbor.loads(d[1]) for d in descriptions}

    def close(self):
        [db.close() for db in (self.descriptions_db, self.domains_db, self.state_db)]

    def sessions_for_user(self, pk):
        return [s.rid for s in self.sessions.values() if s.pk == pk]

    def all_tunnels(self):
        rtn = []
        for sess in self.sessions.values():
            rtn.extend(sess.tunnels.values())
        return rtn

    def all_clusters(self):
        # An occasion may arise where the same cluster is registered twice (swapping over) hence we check for this
        clusters = []
        done_already = set()
        for sess in self.sessions.values():
            for cluster in sess.clusters.values():
                if cluster.fqdn() in done_already:
                    logging.debug("Avoided creating two records for a cluster in all_clusters: " + cluster.fqdn())
                else:
                    clusters.append(cluster)
                    done_already.add(cluster.fqdn())
        return clusters

    def network_topology(self):
        """Returns a list of (subnet_id, external_ip) tuples"""
        topo = [(str(node.subnet_id), node.external_ip) for node in self.nodes.values() if node.external_ip is not None]
        topo.append(("1", Network.external_ip()))
        return topo

    def next_ip(self, node_id):
        smallest = node_id * 65536 + 256  # so the bottom /8 can be used for tunnel addresses i.e. 10.US.0.THEM
        biggest = smallest + 65277  # short enough to miss 255.255 and 255.254
        ip = None
        while ip is None or ip in self.allocations:
            ip = Model.ip_from_int(random.randrange(smallest, biggest))
        self.allocations.add(ip)
        logging.info("Allocated ip: " + ip)
        return ip

    def release_ip(self, ip):
        try:
            self.allocations.remove(ip)
            logging.info("Released ip: " + ip)
        except KeyError:
            logging.debug("Tried to delete an ip, not apparently in table: " + ("None" if ip is None else ip))

    def shed_aged_domains(self):
        # removes aged domains for all users (SLOW)
        for pk in self.domains.keys():
            self.shed_aged_domains_for(pk)

    def shed_aged_domains_for(self, pk):
        # removes domains that are more than 2 hours after their 'attempted' time for this user
        if pk not in self.domains:
            self.domains[pk] = {}
        for dom in list(self.domains[pk].values()):
            if dom.timed_out():
                logging.info("Domain removed due to timeout: " + str(dom.domain))
                del self.domains[pk][dom.domain]
                self.domains_db.mutate("DELETE FROM domains WHERE domain=?;", (dom.domain,))

    def domain_list(self):
        rtn = []
        for pk, user_domains in self.domains.items():
            rtn.append({b64encode(pk).decode(): [d.state() for d in user_domains.values()]})
        return rtn

    def add_global_domain(self, dom):
        if dom.domain in self.global_domains:
            logging.warning("Tried to add a global domain but it was added already.")
            return
        self.global_domains[dom.domain] = dom

    def remove_global_domain(self, dom):
        if dom.domain not in self.global_domains:
            logging.warning("Tried to remove a global domain but it wasn't there.")
            return
        del self.global_domains[dom.domain]

    def create_update_description_record(self, user_pk, image_id, desc):
        full_id = b64encode(user_pk).decode() + image_id
        if full_id in self.descriptions and self.descriptions[full_id] == desc:
            return  # is the one we already had

        self.descriptions[full_id] = desc
        self.descriptions_db.mutate("INSERT OR REPLACE INTO descriptions (full_id,cbor) VALUES (?, ?)",
                                   (full_id, cbor.dumps(desc)))

    def create_session_record(self, sess):
        self.state_db.mutate("INSERT OR REPLACE INTO sessions (rid, cbor) VALUES (?, ?)", (sess.rid, sess.binary()))

    def update_session_record(self, sess):
        self.state_db.mutate("UPDATE sessions SET cbor=? WHERE rid=?", (sess.binary(), sess.rid))

    def delete_session_record(self, rid):
        self.state_db.mutate("DELETE FROM sessions WHERE rid=?", (rid, ))

    def set_forwarding_record(self, key, value):
        self.state_db.mutate("INSERT OR REPLACE INTO forwarding (key, value) VALUES (?, ?)", (key, value))

    def remove_forwarding_record(self, key, value):
        self.state_db.mutate("DELETE FROM forwarding WHERE key=?", (key,))

    def create_domain_record(self, dom, session):
        self.domains_db.mutate("INSERT INTO domains (domain, token, attempted, user, global) VALUES (?, ?, ?, ?, ?)",
                              (dom.domain, dom.token, dom.attempted, session.pk, False))

    def update_domain_record(self, dom):
        self.domains_db.mutate("UPDATE domains SET token=?, attempted=?, global=? WHERE domain=?",
                              (dom.token, dom.attempted, dom.gbl, dom.domain))

    def delete_domain_record(self, dom):
        self.domains_db.mutate("DELETE FROM domains WHERE domain=?", (dom,))

    def resources(self, user_pk):
        """Return a resource offer"""
        # ensure we can reference the user
        if user_pk not in self.domains:
            self.domains[user_pk] = {}  # map domain name to domain object

        # See if any domains have timed out
        self.shed_aged_domains_for(user_pk)

        # Go
        nodes = [(node.pk, node.perf_counters) for node in self.nodes.values()]
        volumes = [{'uuid': vol.uuid, 'tag': vol.tag}
                   for vol in self.volumes.values() if vol.user == user_pk]
        externals = [{'tag': ctr.tag, 'uuid': ctr.uuid, 'ip': ctr.ip, 'node': ctr.node_pk}
                     for ctr in self.containers.values() if ctr.tag is not None and ctr.user == user_pk]
        domains = [{'domain': dom.domain, 'global': dom.is_global()}
                   for dom in self.domains[user_pk].values() if dom.is_valid()]
        domains.extend([{'domain': dom.domain, 'global': dom.is_global()}
                        for dom in self.global_domains.values() if dom.is_valid() and dom.user != user_pk])

        # Return the resource list
        return {'nodes': nodes, 'volumes': volumes, 'externals': externals, 'domains': domains}

    @staticmethod
    def ip_from_int(n):
        return "10.%d.%d.%d" % (n // 65536, (n // 256) % 256, n % 256)

    def __repr__(self):
        return "<model.model.Model object at %x>" % id(self)
