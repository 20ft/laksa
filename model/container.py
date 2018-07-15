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

# Container objects are so the node can be told which containers to destroy when a session disappears.
# We're specifically *not* trying to maintain a full copy of the state on the node.

from tfnz import Taggable
from base64 import b64encode
from binascii import hexlify


class Container(Taggable):
    def __init__(self, user, uuid, tag, session_rid, node_pk, ip, volumes):
        super().__init__(user, uuid, tag)
        self.node_pk = node_pk
        self.session_rid = session_rid
        self.ip = ip
        self.volumes = volumes

    def as_dict(self):
        return ({"user": self.user,
                 "uuid": self.uuid,
                 "tag": self.tag,
                 "session": self.session_rid,
                 "node_pk": self.node_pk,
                 "ip": self.ip,
                 "volumes": self.volumes})

    @staticmethod
    def from_dict(elements):
        return Container(elements['user'],
                         elements['uuid'],
                         elements['tag'],
                         elements['session'],
                         elements['node_pk'],
                         elements['ip'],
                         elements['volumes'])

    def state(self):
        return {'ip': self.ip,
                'volumes': [v.decode() for v in self.volumes],
                'node': b64encode(self.node_pk).decode(),
                'session': hexlify(self.session_rid).decode()}

    def __repr__(self):
        return "<model.container.Container object at %x (uuid=%s session=%s)>" % (id(self), self.uuid, self.session_rid)
