# (c) David Preece 2016-2017
# davep@polymath.tech : https://polymath.tech/ : https://github.com/rantydave
# This work licensed under the Non-profit Open Software Licence version 3 (https://opensource.org/licenses/NPOSL-3.0)
# For commercial licensing see https://20ft.nz/
"""The broker and business logic between clients and nodes"""

# pip3 install py3dns shortuuid requests cbor boto3 awsornot litecache messidge

from awsornot.log import LogHandler
from broker import Broker


def main():
    # basic objects...
    log = LogHandler('20ft', 'broker', ['Starting new HTTP connection'])
    broker = Broker()

    # run the broker
    try:
        broker.run()
    finally:
        # closing
        broker.stop()
        log.stop()


if __name__ == "__main__":
    main()
