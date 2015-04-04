import socket
import threading
import socketserver
import json

from console import debug


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


def connect(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ip, port))
    return sock


def send(sock, data):
    try:
        debug('Sending:', data)
        sock.sendall(bytes(json.dumps(data), 'ascii'))

        data = ''
        while not data.endswith('\n'):
            data += str(sock.recv(1024), 'ascii')

        debug('Received:', data)

        return json.loads(data)

    except OSError:
        debug('Socket closing')
        sock.close()


def requestHandlerFactory(data_handler):
    class ThreadedTCPRequestHandler(socketserver.StreamRequestHandler):
        def __init__(self, *args):
            self.data_handler = data_handler
            super().__init__(*args)

        def handle(self):
            while True:
                data = self.rfile.readline()
                if not data: break

                data = json.loads(str(data, 'ascii'))

                response = self.data_handler(self.request, data)
                self.request.sendall(bytes(json.dumps(response) + '\n', 'ascii'))

    return ThreadedTCPRequestHandler


def start(data_handler):
    # Port 0 means to select an arbitrary unused port
    HOST, PORT = '0.0.0.0', 0

    server = ThreadedTCPServer((HOST, PORT), requestHandlerFactory(data_handler))
    ip, port = server.server_address

    # Start a thread with the server -- that thread will then start one
    # more thread for each request
    server_thread = threading.Thread(target=server.serve_forever)
    # Exit the server thread when the main thread terminates
    server_thread.daemon = True
    server_thread.start()

    return port, server.shutdown