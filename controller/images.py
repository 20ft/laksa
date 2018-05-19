# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/

import os
import subprocess
import time
import lzma


class Images:
    def __init__(self):
        # ensure the cache directory exists
        os.makedirs("state/layer_cache", exist_ok=True)

        # get all the layers
        subprocess.call('rm state/layer_cache/*.uploading', shell=True, stderr=subprocess.DEVNULL)
        self.cached_layers = {entry for entry in os.listdir("state/layer_cache")}

        # finish init
        self.is_being_uploaded = {}  # maps sha256 to a file being written

    def upload_requirements(self, requirements):
        """Find the necessary layers to complete an image"""
        required_layers = set(requirements)  # dedupe
        if None in required_layers:
            required_layers.remove(None)  # any None's that arrived
        if len(required_layers) > 256:
            raise ValueError("Upload offer is too large (>256 layers)")
        rtn_layers = set()
        for layer in requirements:
            if layer in rtn_layers:  # already answered
                continue
            if layer in self.cached_layers:  # do not need to fetch it
                continue
            if layer in self.is_being_uploaded:
                try:
                    stat = os.stat('state/layer_cache/' + layer + '.uploading')
                    since_creation = time.time() - stat.st_mtime
                    if since_creation < 10:  # did we write to the file in the last ten seconds?
                        raise ValueError("Layer is currently being uploaded")
                    os.remove('state/layer_cache/' + layer + '.uploading')
                except FileNotFoundError:
                    pass
            rtn_layers.add(layer)
        return list(rtn_layers)

    def upload_slab(self, sha256, slab, bulk):
        # open files on demand
        try:
            if sha256 not in self.is_being_uploaded:
                self.is_being_uploaded[sha256] = open('state/layer_cache/' + sha256 + '.uploading', "w+b")
        except BaseException as e:
            raise ValueError(e)
        self.is_being_uploaded[sha256].write(lzma.decompress(bulk))
        return "Location received slab: %s" % str(slab + 1)[:16]

    def upload_complete(self, sha256):
        """Place a delivered layer into the database."""
        # is this a layer we're expecting to see?
        self.is_being_uploaded[sha256].close()
        os.rename('state/layer_cache/' + sha256 + '.uploading', 'state/layer_cache/' + sha256)
        # all good
        self.cached_layers.add(sha256)
        del self.is_being_uploaded[sha256]
        return "Location received complete layer: " + sha256[:16]

    def __repr__(self):
        return "<controller.images.Images object at %x (layers=%d)>" % (id(self), len(self.cached_layers))
