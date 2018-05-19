# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/

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
