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
"""Controls an haproxy service"""

# http://cbonte.github.io/haproxy-dconv/1.8/configuration.html#4

import weakref
from subprocess import call, DEVNULL


class HAProxy:
    def __init__(self, model):
        self.model = weakref.ref(model)
        # Ensure file structure
        self.rebuild()

    def rebuild(self):
        before = None
        try:
            with open('haproxy.cfg') as f:
                before = f.read()
        except FileNotFoundError:
            pass

        with open('haproxy.cfg', 'w') as f:
            f.write(HAProxy.header)
            clusters = list(self.model().all_clusters())
            for ssl_section in (False, True):
                f.write('\n\nfrontend http-in\n    bind :80' if not ssl_section else
                        '\n\nfrontend https-in\n    bind :443')

                # ssl
                if ssl_section:
                    for cluster in clusters:
                        if cluster.ssl is not None:
                            f.write(' ssl crt /opt/20ft/laksa/' + cluster.fqdn() + '.ssl')
                    f.write(' alpn http/1.1,http/1.0')

                # compression
                f.write('\n    compression algo gzip')

                # hosts
                for cluster in clusters:
                    if not ssl_section or (cluster.ssl is not None) == ssl_section:
                        f.write("\n    acl %s hdr(host) -i %s" %
                                (HAProxy._aclname(cluster), cluster.fqdn()))

                # acl switches
                for cluster in clusters:
                    if (cluster.ssl is not None) == ssl_section:
                        f.write("\n    use_backend %s if %s" %
                                (HAProxy._backend_name(cluster), HAProxy._aclname(cluster)))
                    else:
                        if not ssl_section:
                            f.write("\n    http-request redirect scheme https if " + HAProxy._aclname(cluster))

            # the backends themselves
            for cluster in clusters:
                f.write('\n\nbackend %s\n' % HAProxy._backend_name(cluster))
                if cluster.rewrite is not None:
                    f.write('    http-request set-header Host %s\n' % cluster.rewrite)
                for container in cluster.containers.values():
                    weight = 10
                    if container.node_pk in self.model().nodes:
                        weight = self.model().nodes[container.node_pk].weight()
                    f.write('    server %s %s:80 weight %d\n' % (container.uuid.decode(), container.ip, weight))
                f.write('\n')

        with open('haproxy.cfg') as f:
            after = f.read()
        if before != after:
            call(['systemctl', 'reload', 'haproxy'], stdout=DEVNULL)

    @staticmethod
    def _aclname(cluster):
        return 'host_' + cluster.fqdn().replace('.', '_')

    @staticmethod
    def _backend_name(cluster):
        return 'backend_' + cluster.fqdn().replace('.', '_')

    # note http-server-close closes the connection to the server but the client still gets http keep alive
    header = """
global
    daemon
    maxconn 512

defaults
    mode http
    timeout connect 5s
    timeout client 50s
    timeout server 50s
    option forwardfor
    option dontlog-normal"""

    def __repr__(self):
        return "<controller.haproxy.HAProxy object at %x (clusters=%d)>" % (id(self), len(self.model().all_clusters()))
