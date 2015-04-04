import socket
import threading
import socketserver
import json

from console import debug


END = '<END>'


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


def connect(ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((ip, port))
    return sock


def send(sock, data, async):
    try:
        debug('Sending:', data)
        sock.sendall(bytes(json.dumps(data) + END, 'ascii'))

        if not async:
            return receive(sock)

    except OSError:
        debug('Socket closing')
        sock.close()


# def receive(sock):
#     data = ''
#     while not data.endswith('\n') and data is not None:
#         d=sock.recv(1024)
#         debug('  D:', repr(d))
#         data += str(d, 'ascii')

#     debug('Received:', data)
#     return data if data is None else json.loads(data)

def receive(the_socket):
    total_data = []
    data = ''
    while True:
        debug('Waiting')
        data = str(the_socket.recv(8192), 'ascii')
        if END in data:
            total_data.append(data[:data.find(END)])
            break
        total_data.append(data)
        if len(total_data) > 1:
            # Check if end_of_data was split
            last_pair = total_data[-2] + total_data[-1]
            if END in last_pair:
                total_data[-2] = last_pair[:last_pair.find(END)]
                total_data.pop()
                break
    debug('Received:', repr(json.loads(''.join(total_data)))
    return json.loads(''.join(total_data))


def requestHandlerFactory(data_handler):
    class ThreadedTCPRequestHandler(socketserver.BaseRequestHandler):
        def __init__(self, *args):
            self.data_handler = data_handler
            super().__init__(*args)

        def handle(self):
            debug('-=-=-=-=-=-=-=-=-=-=-=-=-= New Handler =-=-=-=-=-=-=-=-=-=-=-=-=-')
            self.request.setblocking(True)
            while True:
                data = receive(self.request)
                if not data: break

                response = self.data_handler(self.request, data)
                debug('Sending:', json.dumps(response))
                self.request.sendall(bytes(json.dumps(response) + END, 'ascii'))

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
