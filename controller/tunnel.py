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
"""A 'forward' tunnel onto a container"""
# Note that the passed parameter "proxy" always refers to the remote end

import time
import logging
import socket
import weakref


class Tunnel:

    def __init__(self, uuid, parent, broker, loop, ip, port, timeout):
        logging.debug("Creating tunnel onto: %s:%s" % (ip, port))
        self.uuid = uuid
        self.parent = weakref.ref(parent)
        self.broker = weakref.ref(broker) if broker is not None else None
        self.loop = weakref.ref(loop) if loop is not None else None
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.apparently_connected = {}
        self.proxies = {}  # map of local fd to the socket object
        self.remotepxyfd_localpxyfd = {}  # a map of remote proxy fd to local
        self.localpxyfd_remotepxyfd = {}  # a map of local proxy fd to remote
        self.retries = {}  # remotepxy to a list of method calls to be retried (usually waiting for tcp handshake)

    def as_dict(self):
        return {'uuid': self.uuid, "ip": self.ip, "port": self.port, "timeout": self.timeout}

    @staticmethod
    def from_dict(elements, parent):
        return Tunnel(elements['uuid'], parent, None, None, elements['ip'], elements['port'], elements['timeout'])

    def set_broker_and_loop(self, broker, loop):
        # used when recreating from storage
        self.broker = weakref.ref(broker)
        self.loop = weakref.ref(loop)

    def disconnect(self):
        self.loop().unregister_on_idle(self.retry)  # might be because of retries
        self.disconnect_all_proxies()
        self.broker = None
        self.loop = None

    def disconnect_all_proxies(self):
        logging.debug("Marking all proxies as being disconnected for: " + self.uuid.decode())
        for proxy in list(self.remotepxyfd_localpxyfd.keys()):
            self.close_proxy(proxy)

    def forward(self, msg):
        """"Forwards a tcp connection (or its data) onto the container."""
        remotepxyfd = msg.params['proxy']

        # do we need to create a fresh connection?
        if remotepxyfd not in self.remotepxyfd_localpxyfd:
            self.apparently_connected[remotepxyfd] = False
            proxy = socket.socket()
            proxy.setblocking(False)
            localpxyfd = proxy.fileno()
            self.proxies[localpxyfd] = proxy
            self.remotepxyfd_localpxyfd[remotepxyfd] = localpxyfd
            self.localpxyfd_remotepxyfd[localpxyfd] = remotepxyfd
            self.loop().register_exclusive(localpxyfd, self.incoming)

        if not self.apparently_connected[remotepxyfd]:
            localpxyfd = self.remotepxyfd_localpxyfd[remotepxyfd]
            proxy = self.proxies[localpxyfd]
            logging.debug("Opening a new proxy from remotepxyfd=%d to localpxyfd=%d" % (remotepxyfd, localpxyfd))
            try:
                proxy.connect((self.ip, self.port))
            except (ConnectionRefusedError, ConnectionAbortedError):
                logging.debug("Connection refused, queueing: " + str(msg))
                self.queue_for_retry(remotepxyfd, msg)
                return
            except BlockingIOError:
                pass
                # it throws to let us know the operation is in progress. thanks, Ray.

        # send the data
        localpxyfd = self.remotepxyfd_localpxyfd[remotepxyfd]
        try:
            self.proxies[localpxyfd].sendall(msg.bulk)
            logging.debug("Proxy delivered data: " + str(localpxyfd))
            self.apparently_connected[remotepxyfd] = True
        except OSError as e:
            # queue for retry.
            if e.errno in (11, 32, 134, 111):
                logging.debug("Sendall gave err (%s) for fd: %s" % (str(e), str(localpxyfd)))
                self.queue_for_retry(remotepxyfd, msg)
            else:
                msg.reply({'exception': 'Something unexpected happened connecting the proxy'})
                logging.warning("Connecting (%s:%s) threw: %s" % (self.ip, self.port, str(e)))

    def incoming(self, localpxyfd):
        """Send data that has come in through a proxy back to the client."""
        try:
            remotepxy = self.localpxyfd_remotepxyfd[localpxyfd]
        except KeyError:
            logging.debug("Trying to send data back for proxy that has been closed: " + str(localpxyfd))
            return

        # otherwise we should be all good
        try:
            bulk = self.proxies[localpxyfd].recv(8192)
        except (ConnectionRefusedError, ConnectionResetError, ConnectionAbortedError, TimeoutError, OSError) as e:
            # may be receiving a closed event because the container is rebooting
            # these get marked as not being connected as part of disconnect_all_proxies
            # (itself part of rebooting a container)
            if not self.apparently_connected[remotepxy]:
                return
            logging.debug("Connection failed on recv, treating as if the socket was closed: " + str(localpxyfd))
            bulk = b''

        # is this a socket close event
        if len(bulk) == 0:
            if not self.apparently_connected[remotepxy]:
                return
            logging.debug("Proxy has been closed server side, sending notification: " + str(localpxyfd))
            self.close_proxy(remotepxy)
            return

        # OK, then
        self.broker().send_cmd(self.parent().rid, b'from_proxy', {'proxy': remotepxy}, bulk=bulk, uuid=self.uuid)
        logging.debug("Proxy returned data: " + str(localpxyfd))

    def retry(self):
        """See if we have any messages to retry"""
        self.loop().unregister_on_idle(self.retry)  # will be re-registered if a forward fails again
        for proxy, waiting in list(self.retries.items()):
            del self.retries[proxy]
            self.forward(waiting)

    def close_proxy(self, remotepxyfd):
        """Close a single proxy"""
        logging.debug("...closing proxy connection remote fd: " + str(remotepxyfd))
        localpxyfd = self.remotepxyfd_localpxyfd[remotepxyfd]
        proxy = self.proxies[localpxyfd]  # the actual socket
        proxy.close()
        if remotepxyfd in list(self.retries):
            del self.retries[remotepxyfd]
        del self.remotepxyfd_localpxyfd[remotepxyfd]
        del self.localpxyfd_remotepxyfd[localpxyfd]
        del self.proxies[localpxyfd]
        del self.apparently_connected[remotepxyfd]
        self.loop().unregister_exclusive(localpxyfd)
        return

    def queue_for_retry(self, remotepxyfd, msg):
        # timeout?
        if msg.time is None:
            msg.time = time.time()
        if time.time() - msg.time > self.timeout:
            failure = "Tunnel (%s) timed out trying to connect to: %s:%s" % (self.uuid, self.ip, self.port)
            logging.info(failure)
            self.close_proxy(remotepxyfd)
            msg.reply(results={'exception': failure})
            return

        # OK, go ahead
        logging.debug("Queued a retry (at %f secs) for remote fd: %s" % (time.time() - msg.time, str(remotepxyfd)))
        self.retries[remotepxyfd] = msg
        self.loop().register_on_idle(self.retry)

        # debug
        logging.debug("Retry queue: " + str(self.retries))

    def state(self):
        return {'dest_ip_port': (self.ip, self.port), 'apparently_connected': self.apparently_connected}

    def __repr__(self):
        return "<controller.tunnel.Tunnel object at %x (%s:%s - uuid=%s)>" % (id(self), self.ip, self.port, self.uuid)
