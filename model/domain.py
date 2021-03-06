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

import time
from base64 import b64encode


class Domain:
    """A domain claimed or in the process of being claimed by a user"""
    def __init__(self, domain, token, user, attempted=None, gbl=False):
        self.domain = domain
        self.token = token
        self.user = user
        self.attempted = attempted if attempted is not None else time.time()
        self.gbl = gbl

    def mark_as_valid(self):
        self.token = None

    def is_valid(self):
        return self.token is None

    def timed_out(self):
        if self.is_valid():
            return False
        # if more than six hours since we started attempting to claim the domain
        return (time.time() - self.attempted) > 21600

    def mark_as_global(self, gbl=True):
        self.gbl = gbl

    def is_global(self):
        return self.gbl

    def state(self):
        return {"user": b64encode(self.user).decode(), "global": self.gbl}
