import zmq
import base64


class UartzClient(object):

    def __init__(self, addr):
        self.addr = addr
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
