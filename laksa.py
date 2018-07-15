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
