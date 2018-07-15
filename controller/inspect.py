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
"""Returns a json doc of current state"""

import json
import weakref
import logging
from base64 import b64encode
from binascii import hexlify
from threading import Thread
from bottle import Bottle, run

inspection_server = Bottle()


class InspectionServer(Thread):
    """A thread for running an inspection server."""
    # used to be factored out, I just left it "as is" when factoring back in again
    parent = None  # done as a class variable because the route method needs to be static
    port = None

    def __init__(self, parent, port):
        super().__init__(target=self.serve, name=str("Inspection server"), daemon=True)
        InspectionServer.parent = weakref.ref(parent)
        InspectionServer.port = port
        self.start()

    @staticmethod
    def serve():
        try:
            logging.info("Started inspection server: 127.0.0.1:" + str(InspectionServer.port))
            run(app=inspection_server, host='127.0.0.1', port=InspectionServer.port, quiet=True)
        except OSError:
            logging.critical("Could not bind inspection server, exiting")
            exit(1)

    @staticmethod
    def stop():
        inspection_server.close()

    def __repr__(self):
        return "<tfnz.InspectionServer object at %x>" % id(self)


class LaksaInspection(InspectionServer):
    def __init__(self, parent):
        super().__init__(parent, 1024)

    @staticmethod
    @inspection_server.route('/')
    def state():
        bkr = InspectionServer.parent()

        # flatten owner->domain into just domain
        domains = []
        for owner in bkr.model.domains.keys():
            domains.extend([d for d in bkr.model.domains[owner].values() if d.is_valid()])

        # make a 'unified' state
        rtn = {
            'rid_to_session': {hexlify(r).decode(): s.state() for r, s in bkr.model.sessions.items()},
            'rid_to_node': {hexlify(r).decode(): bkr.model.nodes[pk].state() for r, pk in bkr.node_rid_pk.items()},
            'volumes': [v.global_display_name()for v in bkr.model.volumes.values()],
            'tagged_containers': [ctr.global_display_name() for ctr in bkr.model.containers.values()
                                  if ctr.tag is not None],
            'domains': {d.domain: d.state() for d in domains},
            'allocations': list(bkr.model.allocations)
        }
        return json.dumps(rtn, indent=2) + "\n"
