# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/
"""Initialise incl. aws environment"""

# pkgin -y in python36 py36-pip py36-sqlite3 zeromq
# pip3.6 install pyzmq libnacl py3dns shortuuid psutil lru-dict requests cbor bottle ptyprocess

import subprocess
import os
import logging
import signal
from messidge import KeyPair
from awsornot import ensure_zpool
from awsornot.kv import KeyValue
from awsornot import dynamic_data_or_none, boto_client


class ClusterGlobalState:
    state_mountpoint = '/opt/20ft/laksa/state/'

    def __init__(self, noserver=False):  # noserver implies not spawning the KV server
        self.ssm = KeyValue(ClusterGlobalState.state_mountpoint + 'kvstore', noserver=noserver)
        ensure_zpool('tf')

        # OK, then...
        ip = subprocess.check_output(['hostname', '-I'])[:-1].decode().split()[0]
        self.ssm.put_parameter(
                Name="/20ft/ip",
                Description="Broker VPC IP",
                Type="String",
                Value=ip,
                Overwrite=True
        )

        self.dynamic_data = dynamic_data_or_none()
        if self.dynamic_data:  # we are hooked into AWS
            self.efs = boto_client('efs', self.dynamic_data)
            self.aws = True
        else:  # No AWS
            self.efs = None
            self.aws = False

        # A blank pk to start with (get written in as part of CloudFormation in AWS's case)
        try:
            self.ssm.put_parameter(
                    Name="/20ft/pk",
                    Description="Public Key",
                    Type="String",
                    Value=' ',
                    Overwrite=False
            )
        except:  # if trying to overwrite
            pass

        # read in params
        # pk and sk are b64 text
        self.pk = self.ssm.get_parameter(Name='/20ft/pk')['Parameter']['Value'].encode()
        self.sk = None

        # Classed as a new install if the pk is too short
        new_keys = None
        if len(self.pk) < 44:
            # authentication/encryption
            new_keys = KeyPair.new()
            logging.info("New install being created with pk: " + new_keys.public.decode())
            self.ssm.put_parameter(
                    Name="/20ft/pk",
                    Description="Public Key",
                    Type="String",
                    Value=new_keys.public.decode(),
                    Overwrite=True
            )
            self.pk = new_keys.public
            self.sk = new_keys.secret

        # mount the filesystems?
        if self.efs is not None:
            mounted = False
            mounts = subprocess.check_output(['/bin/mount']).split(b'\n')
            for mount_line in mounts:
                splits = mount_line.split(b' ')
                if len(splits) < 3:
                    continue
                if splits[2].decode() == ClusterGlobalState.state_mountpoint[:-1]:  # remove the trailing slash
                    mounted = True
                    break

            if not mounted:
                state_filesystem = self.ssm.get_parameter(Name='/20ft/state_fs')['Parameter']['Value']
                nfs_ip = None
                try:
                    nfs_ip = (self.efs.describe_mount_targets(FileSystemId=state_filesystem)
                              ['MountTargets'][0]['IpAddress'])
                except IndexError:
                    logging.critical("Could not find mount target for filesystem: " + state_filesystem)
                    signal.pause()  # if we bounce out it'll just restart and loop.
                logging.info("NFS Mounting: " + nfs_ip + ":/")
                os.makedirs(ClusterGlobalState.state_mountpoint, exist_ok=True)
                subprocess.call(['mount',
                                 '-t', 'nfs4',
                                 '-o', 'nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2',
                                 nfs_ip + ":/", ClusterGlobalState.state_mountpoint])
                username = subprocess.check_output(['whoami'])[:-1].decode()
                subprocess.call(['chown', '-R', '%s:%s' % (username, username), 'state'])

        # read sk (or write it if this is the first time through) - needs to be after the state fs has been mounted
        if new_keys is None:
            try:
                with open(ClusterGlobalState.state_mountpoint + '.sk', 'r+b') as f:
                    self.sk = f.read()
            except FileNotFoundError:
                logging.critical("The secret key was not found - \n"
                                 "the most likely cause is a /20ft/pk parameter left over from a previous stack.\n"
                                 "If you remove that and try again a new key pair will be created...\n\n")
                exit(1)
        else:
            with open(ClusterGlobalState.state_mountpoint + '.sk', 'w') as f:
                f.write(self.sk.decode())

    def stop(self):
        self.ssm.stop()
