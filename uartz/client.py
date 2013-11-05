import base64
from collections import namedtuple

import zmq
from zmq.eventloop.zmqstream import ZMQStream


UartzMsg = namedtuple("UartzMsg", "dev msg")


class UartzClient(object):

    def __init__(self, addr):
        self.addr = addr
        self.sock = None
        self.reset_sock()

    def reset_sock(self):
        ctx = zmq.Context.instance()
        self.sock = ctx.socket(zmq.REQ)
        self.sock.connect(self.addr)

    def _do_command(self, command, **kwargs):
        self.sock.send_json(dict(command=command, **kwargs))
        return self.sock.recv()

    def open_uart(self, path, baud=9600):
        return self._do_command("OPEN", baud=baud, path=path)

    def close_uart(self, path):
        return self._do_command("CLOSE", path=path)

    def write_uart(self, path, data):
        encoded = base64.b64encode(data).decode('ascii')
        return self._do_command("WRITE", path=path, data=encoded)


class UartzStream(object):

    def __init__(self, addr, io_loop=None):
        self.addr = addr
        self.ioloop = io_loop

        self.stream = None
        self.reset_stream()

    def reset_stream(self):
        ctx = zmq.Context.instance()
        sock = ctx.socket(zmq.SUB)
        sock.connect(self.addr)
        sock.setsockopt(zmq.SUBSCRIBE, b'')

        self.stream = ZMQStream(sock, self.ioloop)
        self.stream.on_recv(self._handle_msg)

    def _handle_msg(self, msg):
        assert len(msg) == 1
        msg = msg[0]
        chan_idx = msg.index(b":")

        assert chan_idx > 0
        self.handle_msg(UartzMsg(dev=msg[:chan_idx],
                                 msg=msg[chan_idx + 1:]))
