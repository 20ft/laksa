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

from subprocess import call, check_output, DEVNULL, CalledProcessError
from base64 import b64encode, b64decode
import logging
from tfnz import Taggable, TaggedCollection


class Volume(Taggable):
    """A volume that is owned by and mounted by a client"""
    # http://list.zfsonlinux.org/pipermail/zfs-discuss/2015-December/024087.html
    # https://linux.die.net/man/5/exports
    share_options = 'sharenfs=rw,no_subtree_check,crossmnt,all_squash,anonuid=0,anongid=0'

    def __init__(self, user, uuid, tag=None):
        super().__init__(user, uuid, tag=tag)

    def name(self):
        return 'tf/vol-' + self.uuid.decode()

    @staticmethod
    def create(user, uuid, tag, async):
        name = 'tf/vol-' + uuid.decode()
        user_ascii = b64encode(user).decode()[:-1]
        zfs_reply = check_output(['zfs', 'create',
                                  '-o', 'recordsize=8k',
                                  '-o', 'atime=off',
                                  '-o', Volume.share_options,
                                  '-o', 'sync=' + ('disabled' if async else 'standard'),
                                  '-o', ':user=' + user_ascii,
                                  '-o', ':tag=' + (tag.decode() if tag is not None else '-'),
                                  name])
        if zfs_reply != b'':
            logging.error("Tried to create a volume but failed: " + zfs_reply.decode()[:-2])
            raise ValueError("There was a server failure")
        call(['zfs', 'snapshot', name + "@initial"], stdout=DEVNULL)
        # call(['zfs', 'unmount', name])  # IMPORTANT: Don't unmount, it stops NFS from working
        logging.info("Created (for %s) volume: %s" % (user_ascii, name))
        return Volume(user, uuid, tag)

    def snapshot(self):
        call(['zfs', 'destroy', self.name() + "@initial"], stdout=DEVNULL)
        call(['zfs', 'snapshot', self.name() + "@initial"], stdout=DEVNULL)

    def rollback(self):
        call(['zfs', 'rollback', self.name() + "@initial"], stdout=DEVNULL)

    def destroy(self):
        # destroy -r does the snapshot as well
        # note that zfs is quite happy to destroy a filesystem remotely mounted over nfs - which was nice
        call(['zfs', 'destroy', '-r', self.name()])
        logging.info("Destroyed volume: " + self.name())

    @staticmethod
    def all():
        zfs_list = check_output(['zfs', 'list', '-H', '-o', 'name'])
        zfs_list = str(zfs_list, 'ascii').split('\n')

        # return a list of objects created using the metadata
        rtn = TaggedCollection()
        volumes = [fs for fs in zfs_list if len(fs) > 7 and fs[:7] == 'tf/vol-']
        for volume in volumes:
            user = check_output(['zfs', 'get', '-H', '-o', 'value', ':user', volume]).decode()
            if user == '-\n':  # zfs get prints a - when the property is blank
                continue
            tag = check_output(['zfs', 'get', '-H', '-o', 'value', ':tag', volume]).decode()
            tag = None if tag == '-\n' else tag[:-1]
            uuid = volume[7:].encode()
            user_bin = b64decode(user[:-1] + "=")  # -1 is the /n
            vol = Volume(user_bin, uuid, tag)
            logging.info("Found volume: %s" % vol.global_display_name())
            rtn.add(vol)
            call(['zfs', 'set', Volume.share_options, volume])  # linux nfs doesn't initialise sharing from zfs metadata

        return rtn

    def __repr__(self):
        return "<files.volumes.Volume object at %x (%s)>" % (id(self), self.global_display_name())
