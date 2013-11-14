import json
import logging
import base64
import serial

from collections import defaultdict
from tornado import gen

import zmq
from zmq.eventloop import ioloop
from zmq.eventloop.ioloop import DelayedCallback
from zmq.eventloop.zmqstream import ZMQStream


class UartBridge(object):

    def __init__(self, executor, io_loop=None):
        self.ioloop = io_loop or ioloop.IOLoop.instance()
        self.executor = executor

        ctx = zmq.Context.instance()
        self.pub_sock = ctx.socket(zmq.PUB)

        self.uarts = {}
        self.uart_fd = {}
        self.uart_cb = {}
        self.uart_wb = defaultdict(list)

    def bind(self, addr):
        self.pub_sock.bind(addr)

    def open_uart(self, path, **args):
        if path in self.uarts:
            return

        uart_future = self.uarts[path] = self.executor.submit(
            self._open_uart, path, **args)

        self.ioloop.add_future(uart_future, self._open_uart_callback)
        return uart_future

    def _open_uart(self, path, baud, **args):
        try:
            logging.info("Opening %r...")
            uart = serial.Serial(path, baud, timeout=0.5)
            uart.create_args = args
            logging.info("Opened %r.")
        except:
            return False, path, None
        else:
            return True, path, uart

    def _open_uart_callback(self, future, *args):
        success, path, uart = future.result()
        if not success:
            self.uarts.pop(path, None)
            return

        self.uarts[path] = uart
        self.uart_fd[uart.fileno()] = uart

        if path in self.uart_cb:
            self.uart_cb[path].stop()
            del self.uart_cb[path]
        self.update_handler(uart)

    def close_uart(self, path):
        uart = self.uarts.get(path)
        if uart is None:
            return
        self.remove_uart(uart)

    def update_handler(self, uart):
        if not uart.isOpen():
            return

        self.ioloop.remove_handler(uart.fileno())
        if uart.name not in self.uarts:
            return

        events = ioloop.IOLoop.READ
        if self.uart_wb.get(uart.name):
            events |= ioloop.IOLoop.WRITE

        self.ioloop.add_handler(uart.fileno(), self.handle_uart_event, events)

    def write_uart(self, path, data):
        uart = self.uarts.get(path)
        if not uart:
            return

        self.uart_wb[path].append(data)
        self.update_handler(uart)

    def remove_uart(self, uart):
        self.ioloop.remove_handler(uart.fileno())
        del self.uarts[uart.name]
        del self.uart_fd[uart.fileno()]
        self.uart_wb.pop(uart.name, None)

    def handle_uart_event(self, fd, events):
        uart = self.uart_fd.get(fd)
        if not uart:
            return

        if events & ioloop.IOLoop.READ:
            self.handle_uart_read(uart)

        if events & ioloop.IOLoop.WRITE:
            self.handle_uart_write(uart)

        self.update_handler(uart)

    def handle_uart_read(self, uart):
        name = uart.name.encode('utf8')
        try:
            data = uart.read(4096)
        except (OSError, TypeError):   # this is a pyserial bug
            self.handle_uart_error(uart)
        else:
            self.pub_sock.send(name + b":" + data)

    def handle_uart_write(self, uart):
        data = b''.join(self.uart_wb[uart.name])
        count = uart.write(data)

        if count < len(data):
            remaining = [data[count:]]
        else:
            remaining = []
        self.uart_wb[uart.name][:] = remaining

    def handle_uart_error(self, uart):
        self.remove_uart(uart)
        uart.close()
        self.watch_for_device(
            uart.name, baud=uart.baudrate, **uart.create_args)

    def watch_for_device(self, path, **opts):
        def _add_callback(future):
            success, _, _ = future.result()
            if not success:
                cb = self.uart_cb[path] = DelayedCallback(
                    _check_device, 500, self.ioloop)
                cb.start()

        def _check_device():
            uart_future = self.open_uart(path, **opts)
            if uart_future:
                self.ioloop.add_future(uart_future, _add_callback)

        _check_device()


class BridgeController(object):

    def __init__(self, bridge, io_loop=None):
        self.ioloop = io_loop or ioloop.IOLoop.instance()
        self.bridge = bridge

        ctx = zmq.Context.instance()
        self.sock = ctx.socket(zmq.ROUTER)

        self.stream = stream = ZMQStream(self.sock, io_loop=self.ioloop)
        stream.on_recv(self.handle_recv)

    def bind(self, addr):
        self.sock.bind(addr)

    def _reply(self, addr, resp):
        data = json.dumps(resp).encode('utf8')
        self.stream.send_multipart([addr, b'', data])

    @gen.coroutine
    def handle_recv(self, msg):
        addr, _, cmd = msg
        try:
            cmd = json.loads(cmd.decode('utf8'))
        except Exception as e:
            logging.exception("Command decode failed.")
            return self._reply(addr, {
                "status": "FAIL",
                "message": "Message decode failed",
                "exception": str(e)
            })

        logging.debug("Got Command: %r", cmd)
        handlers = {
            "OPEN": self.handle_cmd_open,
            "CLOSE": self.handle_cmd_close,
            "WRITE": self.handle_cmd_write
        }

        handler = handlers.get(cmd.get('command'))
        if handler is None:
            return self._reply(addr, {
                "status": "FAIL",
                "message": "Invalid command"
            })

        try:
            result = yield handler(cmd)
        except Exception as e:
            return self._reply(addr, {
                "status": "FAIL",
                "message": "Exception while handling command",
                "exception": str(e)
            })
        else:
            return self._reply(addr, {
                "status": "OK",
                "message": "Complete",
                "result": result
            })

    @gen.coroutine
    def handle_cmd_open(self, msg):
        uart_path = msg["path"]
        baud = int(msg.get("baud")) or 9600
        try:
            uart_future = self.bridge.open_uart(uart_path, baud=baud)
        except:
            logging.exception("UART Open Failed.")
        yield gen.YieldFuture(uart_future)

    @gen.coroutine
    def handle_cmd_close(self, msg):
        uart_path = msg["path"]
        self.bridge.close_uart(uart_path)

    @gen.coroutine
    def handle_cmd_write(self, msg):
        uart_path = msg["path"]
        data = msg["data"].encode('utf8')
        data = base64.b64decode(data)

        self.bridge.write_uart(uart_path, data)
